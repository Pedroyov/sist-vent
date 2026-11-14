from django.contrib import admin

from .models import Comentario, Competencia, Conducta, ConfigEvaluacion, Nota


@admin.register(Competencia)
class CompetenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "curso", "orden", "activo"]
    list_filter = ["curso__nivel", "curso", "activo"]


@admin.register(ConfigEvaluacion)
class ConfigEvaluacionAdmin(admin.ModelAdmin):
    list_display = ["anio_lectivo", "nivel", "escala", "por_competencia", "conducta"]


@admin.register(Nota)
class NotaAdmin(admin.ModelAdmin):
    list_display = ["alumno", "asignacion", "periodo", "competencia", "numero", "letra"]
    list_filter = ["periodo", "asignacion__curso"]
    search_fields = ["alumno__apellido_paterno", "alumno__numero_documento"]


admin.site.register(Comentario)
admin.site.register(Conducta)
