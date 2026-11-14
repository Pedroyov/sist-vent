from django.urls import path

from . import views

app_name = "evaluacion"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("registro/<int:asignacion_pk>/", views.registro, name="registro"),
    path("conducta/<int:seccion_pk>/", views.conducta, name="conducta"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("competencias/", views.competencias, name="competencias"),
    path("avance/", views.avance, name="avance"),
    path("libreta/<int:alumno_pk>/", views.libreta, name="libreta"),
    path("libretas/seccion/<int:seccion_pk>/", views.libretas_seccion, name="libretas_seccion"),
    path("siagie/seccion/<int:seccion_pk>/", views.consolidado_siagie, name="consolidado_siagie"),
    path("siagie/", views.siagie_llenar, name="siagie"),
    path("siagie/revisar/", views.siagie_revisar, name="siagie_revisar"),
]
