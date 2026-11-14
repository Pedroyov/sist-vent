from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import LoginForm

admin.site.site_header = f"{settings.COLEGIO_NOMBRE} · Administración"
admin.site.site_title = settings.COLEGIO_NOMBRE_CORTO
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
    path("alumnos/", include("alumnos.urls")),
    path("cobranza/", include("cobranza.urls")),
    path("programacion/", include("academico.urls")),
    path("asistencia/", include("asistencia.urls")),
    path("personal/", include("personal.urls")),
    path("notas/", include("evaluacion.urls")),
    path("", include("core.urls")),
]

