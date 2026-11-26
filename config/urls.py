from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views_seguridad as seg

admin.site.site_header = f"{settings.NEGOCIO_NOMBRE} · Administración"
admin.site.site_title = settings.NEGOCIO_NOMBRE_CORTO
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("ingresar/", seg.Ingresar.as_view(), name="login"),
    path("ingresar/codigo/", seg.ingresar_codigo, name="ingresar_codigo"),
    path("cuenta/seguridad/", seg.seguridad, name="seguridad"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("cuenta/contrasena/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("cuenta/contrasena/listo/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("productos/", include("productos.urls")),
    path("personal/", include("personal.urls")),
    path("ventas/", include("ventas.urls")),
    path("caja/", include("caja.urls")),
    path("mesas/", include("mesas.urls")),
    path("clientes/", include("clientes.urls")),
    path("reportes/", include("reportes.urls")),
    path("facturacion/", include("facturacion.urls")),
    path("cobranzas/", include("cobranzas.urls")),
    path("reservas/", include("reservas.urls")),
    path("citas/", include("citas.urls")),
    path("compras/", include("compras.urls")),
    path("impresion/", include("impresion.urls")),
    path("", include("core.urls")),
]
if settings.ADMIN_ACTIVO:
    from django.contrib.auth.views import redirect_to_login

    # el admin no tiene ingreso propio: pasa por el del sistema (contraseña, bloqueo y código del celular)
    admin.site.login = lambda request, extra_context=None: redirect_to_login(request.get_full_path())
    urlpatterns.insert(0, path("admin/", admin.site.urls))

