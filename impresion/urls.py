from django.urls import path

from . import views

app_name = "impresion"

urlpatterns = [
    path("", views.cola, name="cola"),
    path("estacion/", views.estacion, name="estacion"),
    path("estacion/siguiente/", views.siguiente, name="siguiente"),
    path("estacion/listo/", views.listo, name="listo"),
    path("enviar/", views.enviar, name="enviar"),
]
