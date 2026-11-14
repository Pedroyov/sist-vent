from django.contrib import admin

from .models import Alumno, AlumnoApoderado, Apoderado, Matricula


class VinculoInline(admin.TabularInline):
    model = AlumnoApoderado
    extra = 0
    autocomplete_fields = ["apoderado"]


class MatriculaInline(admin.TabularInline):
    model = Matricula
    extra = 0


@admin.register(Alumno)
class AlumnoAdmin(admin.ModelAdmin):
    list_display = ["numero_documento", "apellido_paterno", "apellido_materno", "nombres", "fecha_nacimiento"]
    search_fields = ["numero_documento", "apellido_paterno", "apellido_materno", "nombres"]
    inlines = [VinculoInline, MatriculaInline]


@admin.register(Apoderado)
class ApoderadoAdmin(admin.ModelAdmin):
    list_display = ["numero_documento", "apellidos", "nombres", "celular", "email"]
    search_fields = ["numero_documento", "apellidos", "nombres"]


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ["alumno", "anio_lectivo", "seccion", "estado", "fecha"]
    list_filter = ["anio_lectivo", "estado", "seccion__grado__nivel"]
    search_fields = ["alumno__numero_documento", "alumno__apellido_paterno", "alumno__nombres"]
