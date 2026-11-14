from django.urls import path

from . import views

app_name = "caja"

urlpatterns = [
    path("", views.mi_caja, name="mi_caja"),
    path("historial/", views.historial, name="historial"),
    path("<int:pk>/", views.sesion, name="sesion"),
    path("<int:pk>/cerrar/", views.cerrar_caja, name="cerrar"),
    path("<int:pk>/ingreso/", views.nuevo_movimiento, {"tipo": "ingreso"}, name="ingreso"),
    path("<int:pk>/egreso/", views.nuevo_movimiento, {"tipo": "egreso"}, name="egreso"),
]
