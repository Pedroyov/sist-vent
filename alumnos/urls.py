from django.urls import path

from . import pase, views

app_name = "alumnos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("exportar/", views.exportar, name="exportar"),
    path("importar/", views.importar, name="importar"),
    path("importar/plantilla/", views.plantilla, name="plantilla"),
    path("pase-de-anio/", pase.pase_de_anio, name="pase"),
    path("apoderados/buscar/", views.apoderado_buscar, name="apoderado_buscar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/matricular/", views.matricular, name="matricular"),
    path("<int:pk>/apoderados/agregar/", views.apoderado_agregar, name="apoderado_agregar"),
    path("matriculas/<int:pk>/editar/", views.matricula_editar, name="matricula_editar"),
    path("vinculos/<int:pk>/editar/", views.vinculo_editar, name="vinculo_editar"),
    path("vinculos/<int:pk>/quitar/", views.vinculo_quitar, name="vinculo_quitar"),
]
