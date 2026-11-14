from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control


@login_required
def inicio(request):
    from .permisos import puede

    # Quien solo trabaja en cocina va directo a su pantalla
    if puede(request.user, "mesas.cocina") and not puede(request.user, "mesas.atender", "mesas.cobrar", "ventas.vender",
                                                         "ventas.ver", "productos.ver", "config.negocio"):
        from django.shortcuts import redirect

        return redirect("mesas:cocina")
    from .tablero import Tablero

    t = Tablero(request.user).construir()
    return render(request, "core/inicio.html", {"t": t})


@cache_control(max_age=300)
def manifest(request):
    from .models import Ajustes

    c = Ajustes.cargar()
    if c.tiene_logo:
        iconos = [
            {"src": c.icono_url(192), "sizes": "192x192", "type": "image/png"},
            {"src": c.icono_url(512), "sizes": "512x512", "type": "image/png"},
            {"src": c.icono_url(512), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
    else:
        iconos = [
            {"src": static("img/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("img/icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("img/icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
    data = {
        "name": c.nombre_mostrar,
        "short_name": c.corto_mostrar,
        "description": "Sistema de ventas",
        "lang": "es-PE",
        "start_url": reverse("core:inicio"),
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": c.color or "#0d6efd",
        "icons": iconos,
    }
    return JsonResponse(data, content_type="application/manifest+json")


@cache_control(no_cache=True)
def service_worker(request):
    response = render(
        request,
        "core/sw.js",
        {
            "static_prefix": "/" + settings.STATIC_URL.lstrip("/"),
            "precache": [
                reverse("core:offline"),
                static("vendor/adminlte/adminlte.min.css"),
                static("vendor/adminlte/adminlte.min.js"),
                static("vendor/bootstrap/bootstrap.bundle.min.js"),
                static("vendor/bootstrap-icons/bootstrap-icons.min.css"),
                static("vendor/htmx/htmx.min.js"),
                static("css/app.css"),
                static("js/app.js"),
                static("img/icons/icon-192.png"),
            ],
        },
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "core/offline.html")


def archivo(request, ruta):
    """Imágenes subidas: solo para usuarios con permiso (no se publican en /media).
    El logo y los íconos del negocio (negocio/) son públicos: se ven en el ingreso y en el celular.
    Cada app que guarde imágenes agrega su carpeta en `reglas`, por ejemplo
    "productos/": ("productos.ver",)."""
    import mimetypes
    import os

    from django.core.exceptions import PermissionDenied
    from django.http import FileResponse, Http404

    from .permisos import puede

    reglas = {"productos/": ("productos.ver",)}
    publico = ruta.startswith("negocio/") and ruta.count("/") == 1
    permisos = next((p for prefijo, p in reglas.items() if ruta.startswith(prefijo)), None)
    if not publico:
        if permisos is None:
            raise Http404
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not puede(request.user, *permisos):
            raise PermissionDenied
    base = os.path.realpath(settings.MEDIA_ROOT)
    camino = os.path.realpath(os.path.join(base, ruta))
    if not camino.startswith(base + os.sep) or not os.path.isfile(camino):
        raise Http404
    tipo = mimetypes.guess_type(camino)[0] or "application/octet-stream"
    if not tipo.startswith("image/"):
        raise Http404
    resp = FileResponse(open(camino, "rb"), content_type=tipo)
    resp["Cache-Control"] = "public, max-age=86400" if publico else "private, max-age=3600"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
