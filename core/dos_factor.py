"""Segundo factor de ingreso: código de 6 dígitos (TOTP, RFC 6238) de una app del celular.

- Obligatorio para Administración y el superusuario cuando DOS_FACTOR_OBLIGATORIO está encendido
  (por defecto en producción; apagado en la PC local y en las demos). Cualquier otro usuario puede activarlo.
- «Recordar este dispositivo» guarda una cookie firmada por 30 días; cambiar de celular o quitar el
  código la invalida (campo `version`).
- 8 códigos de respaldo de un solo uso por si se pierde el celular. Solo se guarda su huella.
- Los intentos fallidos usan el mismo bloqueo que la contraseña (caché «seguridad», en la base de datos).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.core import signing

PASO = 30
DIGITOS = 6
DIAS_RECORDAR = 30
COOKIE = "dispositivo_seguro"
PENDIENTE = "dos_factor_pendiente"   # en la sesión: quién puso bien su contraseña y falta el código
VERIFICADO = "dos_factor_ok"         # en la sesión: ya no hay que revisar en cada pantalla
MINUTOS_PARA_CODIGO = 5
_LETRAS = "abcdefghjkmnpqrstuvwxyz23456789"  # sin 0/o, 1/l/i


def nuevo_secreto():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(secreto, paso):
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    h = hmac.new(clave, struct.pack(">Q", paso), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    n = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITOS
    return f"{n:0{DIGITOS}d}"


def paso_valido(secreto, codigo, ultimo=0, ahora=None):
    """El paso del código si vale, o None. Acepta un paso antes o después (reloj del celular desfasado)
    y nunca uno ya usado, así un código visto por encima del hombro no sirve dos veces."""
    codigo = "".join(c for c in str(codigo or "") if c.isdigit())
    if len(codigo) != DIGITOS:
        return None
    t = int((ahora if ahora is not None else time.time()) // PASO)
    for p in (t - 1, t, t + 1):
        if p > ultimo and hmac.compare_digest(_codigo(secreto, p), codigo):
            return p
    return None


def enlace_app(secreto, usuario):
    """Lo que lleva el QR: la app del celular lo lee y queda configurada con el nombre del negocio."""
    from .models import Ajustes

    emisor = Ajustes.cargar().nombre_mostrar or "Sistema de ventas"
    etiqueta = quote(f"{emisor}:{usuario.username}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(emisor)}&digits={DIGITOS}&period={PASO}"


def secreto_legible(secreto):
    return " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4))


# --- Códigos de respaldo ---------------------------------------------------------

def _normalizar(codigo):
    return "".join(c for c in str(codigo or "").lower() if c in _LETRAS)


def _huella(codigo):
    return hmac.new(settings.SECRET_KEY.encode(), b"respaldo:" + _normalizar(codigo).encode(), hashlib.sha256).hexdigest()


def nuevos_respaldos(factor, cantidad=8):
    """Genera los códigos, guarda sus huellas y devuelve el texto para mostrarlos una sola vez."""
    codigos = []
    for _ in range(cantidad):
        c = "".join(secrets.choice(_LETRAS) for _ in range(8))
        codigos.append(f"{c[:4]}-{c[4:]}")
    factor.respaldos = [_huella(c) for c in codigos]
    return codigos


def es_respaldo(texto):
    return len(_normalizar(texto)) == 8 and not str(texto).strip().isdigit()


# --- Quién lo necesita -------------------------------------------------------------

def de(usuario):
    from .models import SegundoFactor

    return SegundoFactor.objects.filter(usuario=usuario).first()


def obligatorio(usuario):
    from .permisos import acceso_total

    return bool(getattr(settings, "DOS_FACTOR_OBLIGATORIO", False)) and acceso_total(usuario)


def activo(usuario):
    f = de(usuario)
    return bool(f and f.activo)


# --- Validar al ingresar -----------------------------------------------------------

def validar(usuario, texto):
    """Revisa un código del celular o de respaldo. Devuelve "app", "respaldo" o None. Marca lo usado."""
    from django.db import transaction

    from .bitacora import anotar
    from .models import SegundoFactor

    with transaction.atomic():
        f = SegundoFactor.objects.select_for_update().filter(usuario=usuario, activo=True).first()
        if not f:
            return None
        if es_respaldo(texto):
            h = _huella(texto)
            if h in f.respaldos:
                f.respaldos = [x for x in f.respaldos if x != h]
                f.save(update_fields=["respaldos"])
                anotar("ingreso.respaldo", f"{usuario.get_full_name() or usuario.username} ingresó con un código de respaldo "
                       f"(le quedan {len(f.respaldos)})", objeto=usuario, usuario=usuario)
                return "respaldo"
            return None
        p = paso_valido(f.secreto, texto, f.ultimo_paso)
        if p is None:
            return None
        f.ultimo_paso = p
        f.save(update_fields=["ultimo_paso"])
        return "app"


# --- Recordar el dispositivo ---------------------------------------------------------

def recordar(respuesta, usuario):
    f = de(usuario)
    valor = signing.dumps({"u": usuario.pk, "v": f.version}, salt=COOKIE)
    respuesta.set_cookie(COOKIE, valor, max_age=DIAS_RECORDAR * 86400, httponly=True, samesite="Lax",
                         secure=not settings.DEBUG)


def recordado(request, usuario):
    f = de(usuario)
    if not (f and f.activo):
        return False
    try:
        datos = signing.loads(request.COOKIES.get(COOKIE, ""), salt=COOKIE, max_age=DIAS_RECORDAR * 86400)
    except signing.BadSignature:
        return False
    return datos.get("u") == usuario.pk and datos.get("v") == f.version


# --- En cada pantalla -----------------------------------------------------------------

class SegundoFactorMiddleware:
    """Si el código es obligatorio para este usuario y todavía no lo activó, solo puede ir a activarlo."""
    LIBRES = ("/cuenta/seguridad/", "/salir/", "/static/", "/manifest.webmanifest", "/sw.js", "/offline/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, "user", None)
        if (u is not None and u.is_authenticated and getattr(settings, "DOS_FACTOR_OBLIGATORIO", False)
                and not request.session.get(VERIFICADO) and not request.path.startswith(self.LIBRES)):
            if obligatorio(u):
                if not activo(u):
                    from django.contrib import messages
                    from django.shortcuts import redirect

                    messages.warning(request, "Por seguridad, las cuentas de Administración necesitan el código del celular. Actívalo para continuar.")
                    if request.headers.get("HX-Request"):
                        from django.http import HttpResponse

                        r = HttpResponse(status=204)
                        r["HX-Redirect"] = "/cuenta/seguridad/"
                        return r
                    return redirect("seguridad")
                request.session[VERIFICADO] = True  # ya lo tiene: no se vuelve a consultar en esta sesión
        return self.get_response(request)
