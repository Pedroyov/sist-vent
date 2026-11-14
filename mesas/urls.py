from django.urls import path

from . import views

app_name = "mesas"

urlpatterns = [
    path("", views.mapa, name="mapa"),
    path("abrir/", views.abrir, name="abrir"),
    path("configurar/", views.configurar, name="configurar"),
    path("cuenta/<int:pk>/", views.cuenta, name="cuenta"),
    path("cuenta/<int:pk>/agregar/", views.agregar_vista, name="agregar"),
    path("cuenta/<int:pk>/enviar/", views.enviar, name="enviar"),
    path("cuenta/<int:pk>/comanda/", views.comanda, name="comanda"),
    path("cuenta/<int:pk>/precuenta/", views.precuenta, name="precuenta"),
    path("cuenta/<int:pk>/pedir-cuenta/", views.pedir_cuenta, name="pedir_cuenta"),
    path("cuenta/<int:pk>/cambiar/", views.cambiar_mesa, name="cambiar"),
    path("cuenta/<int:pk>/cobrar/", views.cobrar_vista, name="cobrar"),
    path("cuenta/<int:pk>/anular/", views.anular, name="anular"),
    path("item/<int:pk>/", views.item, name="item"),
]
