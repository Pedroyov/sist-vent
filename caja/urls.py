from django.urls import path

from . import views

app_name = "caja"

urlpatterns = [
    path("", views.mi_caja, name="mi_caja"),
    path("historial/", views.historial, name="historial"),
    path("gastos/", views.lista_gastos, name="gastos"),
    path("gastos/nuevo/", views.gasto_nuevo, name="gasto_nuevo"),
    path("gastos/<int:pk>/anular/", views.gasto_anular, name="gasto_anular"),
    path("cajas/", views.puntos, name="puntos"),
    path("cajas/<int:pk>/", views.punto_editar, name="punto_editar"),
    path("<int:pk>/", views.sesion, name="sesion"),
    path("<int:pk>/cerrar/", views.cerrar_caja, name="cerrar"),
    path("<int:pk>/imprimir/", views.imprimir, name="imprimir"),
    path("<int:pk>/ingreso/", views.nuevo_movimiento, {"tipo": "ingreso"}, name="ingreso"),
    path("<int:pk>/egreso/", views.nuevo_movimiento, {"tipo": "egreso"}, name="egreso"),
]
