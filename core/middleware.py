from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

# En la demo pública cualquiera entra con las claves de prueba: no se permite
# cambiar contraseñas, usuarios, módulos ni entrar al admin de Django.
BLOQUEADAS = ("/cuenta/contrasena/", "/cuenta/seguridad/", "/configuracion/usuarios/", "/configuracion/modulos/", "/admin/")


class ModoDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEMO and request.method == "POST" and request.path.startswith(BLOQUEADAS):
            messages.warning(request, "Esto está desactivado en la demostración (para que todos puedan seguir entrando).")
            return redirect(request.META.get("HTTP_REFERER") or "/")
        if settings.DEMO and request.path.startswith("/admin/"):
            messages.warning(request, "El admin de Django está desactivado en la demostración.")
            return redirect("/")
        return self.get_response(request)
