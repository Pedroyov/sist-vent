import re
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


def inicio_dia(dia):
    """Medianoche (hora local) del día: el límite que sí usa el índice de una fecha con hora."""
    from django.utils import timezone

    return timezone.make_aware(datetime.combine(dia, time.min))


def dias(campo, desde, hasta=None, *, antes_de=None):
    """Filtro de los días locales [desde, hasta] (o [desde, antes_de)) sobre un campo fecha-hora:
    `Venta.objects.filter(**dias("fecha", desde, hasta))`. A diferencia de `fecha__date`, que convierte cada fila a fecha
    local y obliga a recorrer toda la tabla en PostgreSQL, compara contra dos instantes y aprovecha el índice."""
    fin = antes_de if antes_de is not None else (hasta or desde) + timedelta(days=1)
    return {f"{campo}__gte": inicio_dia(desde), f"{campo}__lt": inicio_dia(fin)}


def ip_cliente(request):
    """IP de quien hace la petición. Detrás de N proxies de confianza (settings.PROXIES_CONFIABLES), la N-ésima desde el
    final de X-Forwarded-For (la que agregó nuestro proxy); sin proxies, la de la conexión."""
    from django.conf import settings

    if request is None:
        return ""
    n = getattr(settings, "PROXIES_CONFIABLES", 0)
    if n > 0:
        cadena = [x.strip() for x in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if x.strip()]
        if len(cadena) >= n:
            return cadena[-n][:45]
    return request.META.get("REMOTE_ADDR", "")[:45]


def entero(valor):
    """Convierte a entero un id que llega por GET/POST; None si no es un número (evita errores 500)."""
    texto = str(valor if valor is not None else "").strip()
    return int(texto) if texto.isdigit() else None


def url_segura(request, url, defecto="/"):
    """Solo deja volver a direcciones de este mismo sistema (evita mandar al usuario a otro sitio)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return defecto


def numero_whatsapp(telefono):
    """'987 654 321' -> '51987654321' (para enlaces wa.me). Vacío si no hay número."""
    d = re.sub(r"\D", "", telefono or "")
    if len(d) == 9 and d.startswith("9"):
        d = "51" + d
    return d


def enlace_whatsapp(telefono=None, texto=""):
    """El único lugar donde se arma un enlace de WhatsApp (wa.me), con el mensaje listo si se da `texto`.

    - Con teléfono: abre el chat con esa persona. Si el número no sirve, devuelve "" (para no mostrar el botón).
    - Sin teléfono (None): abre WhatsApp para elegir a quién mandarlo (compartir un ticket, mis horarios…)."""
    from urllib.parse import quote

    if telefono is None:
        base = "https://wa.me/"
    else:
        numero = numero_whatsapp(telefono)
        if not numero:
            return ""
        base = f"https://wa.me/{numero}"
    return f"{base}?text={quote(texto)}" if texto else base


@deconstructible
class TamanoMaximo:
    """Validador: límite de tamaño para archivos subidos (en MB)."""

    def __init__(self, megas=5):
        self.megas = megas

    def __call__(self, archivo):
        if archivo and getattr(archivo, "size", 0) > self.megas * 1024 * 1024:
            raise ValidationError(f"El archivo es muy grande (máximo {self.megas} MB).")

    def __eq__(self, otro):
        return isinstance(otro, TamanoMaximo) and otro.megas == self.megas


_GOOGLE = re.compile(r"^(www\.|maps\.)?google\.(com|com\.[a-z]{2}|[a-z]{2})$")
_COORDS = re.compile(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})")


def enlace_mapa(texto):
    """La ubicación exacta que manda el cliente, lista para abrir en el mapa. El único lugar que la reconoce.

    Acepta lo que se pega desde WhatsApp o una app de mapas: un enlace de Google Maps (también maps.app.goo.gl), Waze o
    Apple Maps, aunque venga con texto alrededor, o coordenadas («-12.0464, -77.0428»). Cualquier otro enlace no se
    acepta (el repartidor solo debe abrir mapas). Devuelve el enlace o "" si no hay ubicación."""
    from urllib.parse import urlsplit

    texto = str(texto or "").strip()
    if not texto:
        return ""
    for url in re.findall(r"https?://[^\s<>\"']+", texto):
        partes = urlsplit(url)
        host = (partes.hostname or "").lower()
        es_mapa = ((_GOOGLE.match(host) and (host.startswith("maps.") or partes.path.startswith("/maps")))
                   or host == "maps.app.goo.gl" or (host == "goo.gl" and partes.path.startswith("/maps"))
                   or host in ("waze.com", "www.waze.com", "ul.waze.com", "maps.apple.com"))
        if es_mapa:
            return url[:300]
    m = _COORDS.search(texto)
    if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
        return f"https://www.google.com/maps/search/?api=1&query={m.group(1)},{m.group(2)}"
    return ""


def qr_svg(texto, tam=110):
    """Código QR en SVG, listo para la plantilla (comprobantes, código del celular)."""
    if not texto:
        return ""
    import io

    import qrcode
    import qrcode.image.svg
    from django.utils.safestring import mark_safe

    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    svg = svg[svg.index("<svg"):].replace("<svg ", f'<svg width="{tam}" height="{tam}" ', 1)
    return mark_safe(svg)


# --- Archivos subidos (disco local o DigitalOcean Spaces: el mismo código para los dos) -------------

def guardar_archivo(nombre, contenido):
    """Guarda (o reemplaza) un archivo subido con ese nombre exacto, por ejemplo «negocio/logo.png»."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    if default_storage.exists(nombre):
        default_storage.delete(nombre)
    return default_storage.save(nombre, ContentFile(contenido))


def imagen_a_bytes(im, formato, **opciones):
    from io import BytesIO

    salida = BytesIO()
    im.save(salida, formato, **opciones)
    return salida.getvalue()
