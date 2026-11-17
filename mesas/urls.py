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
    path("cuenta/<int:pk>/personas/", views.personas, name="personas"),
    path("cuenta/<int:pk>/pedir-cuenta/", views.pedir_cuenta, name="pedir_cuenta"),
    path("cuenta/<int:pk>/cambiar/", views.cambiar_mesa, name="cambiar"),
    path("cuenta/<int:pk>/cobrar/", views.cobrar_vista, name="cobrar"),
    path("cuenta/<int:pk>/anular/", views.anular, name="anular"),
    path("item/<int:pk>/", views.item, name="item"),
    path("cuenta/<int:pk>/liberar/", views.liberar, name="liberar"),
    path("cuenta/<int:pk>/delivery/", views.delivery_accion, name="delivery"),
    path("delivery/", views.pedidos, name="pedidos"),
    path("delivery/nuevo/", views.delivery_nuevo, name="delivery_nuevo"),
    path("delivery/buscar/", views.delivery_buscar, name="delivery_buscar"),
    path("item/<int:pk>/cortesia/", views.cortesia_vista, name="cortesia"),
    path("cuenta/<int:pk>/servido/", views.servido, name="servido"),
    path("cocina/", views.cocina, name="cocina"),
    path("cocina/marcar/", views.cocina_marcar, name="cocina_marcar"),
]
