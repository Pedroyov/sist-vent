from django.urls import path

from . import views

app_name = "citas"

urlpatterns = [
    path("", views.agenda, name="agenda"),
    path("nueva/", views.formulario, name="nueva"),
    path("horarios/", views.horarios, name="horarios"),
    path("mi-agenda/", views.mi_agenda, name="mi_agenda"),
    path("personal/<int:pk>/ausencia/", views.ausencia, name="ausencia"),
    path("ausencia/<int:pk>/borrar/", views.ausencia_borrar, name="ausencia_borrar"),
    path("configurar/", views.configurar, name="configurar"),
    path("registrar/", views.registrar, name="registrar"),
    path("por-cobrar/", views.por_cobrar, name="por_cobrar"),
    path("por-cobrar/ya-cobrado/", views.cobrada_aparte, name="cobrada_aparte"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.formulario, name="editar"),
    path("<int:pk>/<str:accion>/", views.accion, name="accion"),
]
