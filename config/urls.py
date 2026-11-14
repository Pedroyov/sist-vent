from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import LoginForm

admin.site.site_header = f"{settings.NEGOCIO_NOMBRE} · Administración"
admin.site.site_title = settings.NEGOCIO_NOMBRE_CORTO
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path(
        "ingresar/",
        auth_views.LoginView.as_view(
            authentication_form=LoginForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("cuenta/contrasena/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("cuenta/contrasena/listo/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("admin/", admin.site.urls),
    path("productos/", include("productos.urls")),
    path("ventas/", include("ventas.urls")),
    path("caja/", include("caja.urls")),
    path("mesas/", include("mesas.urls")),
    path("", include("core.urls")),
]

