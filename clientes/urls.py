from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.form, name="nuevo"),
    path("buscar/", views.buscar, name="buscar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.form, name="editar"),
    path("<int:pk>/pagar/", views.abonar, name="abonar"),
    path("<int:pk>/imprimir/", views.imprimir, name="imprimir"),
    path("pagos/<int:pk>/anular/", views.anular, name="anular_abono"),
]
