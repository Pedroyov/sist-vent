from django.urls import path

from . import views

app_name = "facturacion"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("reenviar/", views.reenviar, name="reenviar"),
    path("configurar/", views.configurar, name="configurar"),
    path("venta/<int:pk>/emitir/", views.emitir_venta, name="emitir_venta"),
]
