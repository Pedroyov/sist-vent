from django.urls import path

from . import views

app_name = "asistencia"

urlpatterns = [
    path("", views.hoy, name="hoy"),
    path("tomar/<int:seccion_pk>/", views.tomar, name="tomar"),
    path("tomar/<int:seccion_pk>/<int:asignacion_pk>/", views.tomar, name="tomar_curso"),
    path("resumen/", views.resumen, name="resumen"),
    path("resumen/avisar/<int:alumno_pk>/", views.avisar_falta, name="avisar_falta"),
    path("reporte/", views.reporte, name="reporte"),
]
