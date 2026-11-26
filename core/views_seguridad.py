"""Ingreso en dos pasos (contraseña y código del celular) y la pantalla «Seguridad» de cada usuario."""
import time

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dos_factor as df
from .bitacora import anotar
from .forms import LoginForm, bloqueado, contar_fallo
from .models import SegundoFactor
from .permisos import acceso_total_requerido
from .utils import qr_svg, url_segura

User = get_user_model()


class Ingresar(LoginView):
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if df.pide_codigo(user) and not df.recordado(self.request, user):
            pendiente = {"u": user.pk, "t": int(time.time()), "b": user.backend, "next": self.get_success_url(),
                         "metodo": "app" if df.activo(user) else "correo"}
            if pendiente["metodo"] == "correo":
                if not user.email:  # sin correo no hay a dónde mandarlo: entra, pero se le pide ponerlo
                    anotar("ingreso.sin_correo", f"{user.get_full_name() or user.username} entró sin código: su usuario no tiene correo",
                           objeto=user, usuario=user)
                    respuesta = super().form_valid(form)
                    messages.warning(self.request, "Tu usuario no tiene correo: no se pudo pedirte el código. Pide que lo agreguen en Usuarios.")
                    return respuesta
                if not df.enviar_codigo_correo(pendiente, user):
                    messages.error(self.request, "No se pudo enviar el código a tu correo. Intenta en unos minutos; si sigue, llama a soporte.")
                    return redirect("login")
            self.request.session[df.PENDIENTE] = pendiente
            return redirect("ingresar_codigo")
        respuesta = super().form_valid(form)
        if df.pide_codigo(user):
            self.request.session[df.VERIFICADO] = True
        else:
            df.avisar_equipo_nuevo(self.request, respuesta, user)
        return respuesta


def _pendiente(request):
    p = request.session.get(df.PENDIENTE)
    limite = df.MINUTOS_CORREO if p and p.get("metodo") == "correo" else df.MINUTOS_PARA_CODIGO
    if not p or time.time() - p.get("t", 0) > limite * 60:
        request.session.pop(df.PENDIENTE, None)
        return None, None
    return p, User.objects.filter(pk=p["u"], is_active=True).first()


def ingresar_codigo(request):
    """Segundo paso del ingreso. Un código errado cuenta como intento fallido; al bloquearse, vuelve a pedir la contraseña."""
    p, user = _pendiente(request)
    if not user:
        messages.info(request, "Vuelve a escribir tu usuario y contraseña.")
        return redirect("login")
    error = ""
    correo = p.get("metodo") == "correo"
    if request.method == "POST" and correo and request.POST.get("accion") == "reenviar":
        if df.enviar_codigo_correo(p, user):
            p["t"] = int(time.time())
            request.session[df.PENDIENTE] = p
            messages.info(request, "Te enviamos un código nuevo.")
        else:
            messages.error(request, "No se pudo enviar otro código. Vuelve a entrar en unos minutos.")
        return redirect("ingresar_codigo")
    if request.method == "POST":
        codigo = request.POST.get("codigo", "")
        if bloqueado(request, user.username):
            request.session.pop(df.PENDIENTE, None)
            messages.error(request, "Demasiados intentos fallidos. Por seguridad, espera 15 minutos.")
            return redirect("login")
        tipo = ("correo" if df.validar_correo(p, user, codigo) else None) if correo else df.validar(user, codigo)
        if tipo:
            request.session.pop(df.PENDIENTE, None)
            auth_login(request, user, backend=p["b"])
            request.session[df.VERIFICADO] = True
            respuesta = redirect(url_segura(request, p.get("next"), "/"))
            if request.POST.get("recordar"):
                df.recordar(respuesta, user)
            if tipo == "respaldo":
                messages.warning(request, "Usaste un código de respaldo. Si perdiste el celular, entra a Seguridad y cambia de celular.")
            return respuesta
        contar_fallo(request, user.username)
        error = ("El código no es correcto o ya venció. Revisa el último correo o pide uno nuevo." if correo
                 else "El código no es correcto o ya venció. Escribe el que muestra ahora la app.")
    return render(request, "registration/codigo.html", {"error": error, "dias": df.DIAS_RECORDAR, "correo": correo,
                                                       "a_donde": df.correo_oculto(user.email), "reenviar": p.get("envios", 0) < df.ENVIOS_MAX})


@login_required
def seguridad(request):
    """Activar, cambiar de celular, códigos de respaldo y olvidar dispositivos."""
    f = df.de(request.user)
    obligatorio = df.obligatorio(request.user)
    accion = request.POST.get("accion") if request.method == "POST" else None

    if not (f and f.activo):
        secreto = request.session.get("dos_factor_nuevo") or df.nuevo_secreto()
        request.session["dos_factor_nuevo"] = secreto
        error = ""
        if accion == "activar":
            p = df.paso_valido(secreto, request.POST.get("codigo"))
            if p is None:
                error = "El código no coincide. Revisa que la hora del celular esté en automático y escribe el código que se ve ahora."
            else:
                with transaction.atomic():
                    f, _ = SegundoFactor.objects.select_for_update().get_or_create(usuario=request.user, defaults={"secreto": secreto})
                    f.secreto, f.activo, f.activado_en, f.ultimo_paso = secreto, True, timezone.now(), p
                    f.version += 1
                    codigos = df.nuevos_respaldos(f)
                    f.save()
                    anotar("ingreso.2fa_activado", f"{request.user.get_full_name() or request.user.username} activó el código del celular",
                           objeto=request.user)
                request.session.pop("dos_factor_nuevo", None)
                request.session[df.VERIFICADO] = True
                return render(request, "core/seguridad_respaldos.html", {"codigos": codigos, "primera_vez": True})
        return render(request, "core/seguridad.html", {
            "activo": False, "obligatorio": obligatorio, "error": error, "secreto": df.secreto_legible(secreto),
            "qr": qr_svg(df.enlace_app(secreto, request.user), 200),
        })

    if accion:
        if df.paso_valido(f.secreto, request.POST.get("codigo"), f.ultimo_paso) is None:
            messages.error(request, "Para cambiar esto escribe el código que muestra ahora la app del celular.")
            return redirect("seguridad")
        with transaction.atomic():
            f = SegundoFactor.objects.select_for_update().get(pk=f.pk)
            if accion == "respaldos":
                codigos = df.nuevos_respaldos(f)
                f.save(update_fields=["respaldos"])
                return render(request, "core/seguridad_respaldos.html", {"codigos": codigos})
            if accion == "olvidar":
                f.version += 1
                f.save(update_fields=["version"])
                messages.success(request, "Listo: todos los dispositivos recordados volverán a pedir el código.")
            elif accion == "cambiar":
                f.activo, f.respaldos = False, []
                f.version += 1
                f.save(update_fields=["activo", "respaldos", "version"])
                request.session.pop(df.VERIFICADO, None)
                anotar("ingreso.2fa_desactivado", f"{request.user.get_full_name() or request.user.username} quitó el código del celular"
                       + (" para cambiar de celular" if obligatorio else ""), objeto=request.user)
                messages.info(request, "Escanea el nuevo código con el celular." if obligatorio else "Se quitó el código del celular.")
        return redirect("seguridad")
    return render(request, "core/seguridad.html", {"activo": True, "obligatorio": obligatorio, "f": f, "quedan": len(f.respaldos)})


@require_POST
@acceso_total_requerido
def quitar_codigo(request, pk):
    """Para quien perdió el celular y los códigos de respaldo: Administración se lo quita y al ingresar lo vuelve a activar."""
    u = get_object_or_404(User, pk=pk)
    if u == request.user:
        return redirect("seguridad")
    df.quitar(u, por=request.user)
    messages.success(request, f"Listo. {u.get_full_name() or u.username} tendrá que activar el código de nuevo"
                     + (" al ingresar." if df.obligatorio(u) else " si quiere usarlo."))
    return redirect("core:usuario_lista")
