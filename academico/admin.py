from django.contrib import admin

from .models import Asignacion, Curso


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "nivel", "abreviatura", "orden", "activo"]
    list_filter = ["nivel", "activo"]


@admin.register(Asignacion)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ["seccion", "curso", "docente"]
    list_filter = ["seccion__anio_lectivo", "seccion__grado__nivel"]
