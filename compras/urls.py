from django.urls import path

from . import views

app_name = "compras"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/pagar/", views.pagar, name="pagar"),
    path("<int:pk>/anular/", views.anular, name="anular"),
    path("<int:pk>/precios/", views.actualizar_precios, name="actualizar_precios"),
    path("por-pagar/", views.por_pagar, name="por_pagar"),
    path("reponer/", views.reponer, name="reponer"),
    path("proveedores/", views.proveedores, name="proveedores"),
    path("proveedores/nuevo/", views.proveedor, name="proveedor_nuevo"),
    path("proveedores/<int:pk>/", views.proveedor, name="proveedor"),
    path("proveedores/<int:pk>/pagar/", views.pagar_proveedor, name="pagar_proveedor"),
]
