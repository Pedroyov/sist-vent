from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("", views.agenda, name="agenda"),
    path("nueva/", views.formulario, name="nueva"),
    path("<int:pk>/editar/", views.formulario, name="editar"),
    path("<int:pk>/<str:accion>/", views.accion, name="accion"),
    path("historial/", views.buscar_tel, name="historial"),
    path("configurar/", views.configurar, name="configurar"),
]
