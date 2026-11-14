from django.urls import path

from . import views

app_name = "personal"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.formulario, name="nuevo"),
    path("planilla/", views.planilla, name="planilla"),
    path("importar-usuarios/", views.importar_usuarios, name="importar_usuarios"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.formulario, name="editar"),
]
