from django.contrib import admin

from .models import AnioLectivo, Grado, Nivel, Periodo, Seccion


class PeriodoInline(admin.TabularInline):
    model = Periodo
    extra = 0


@admin.register(AnioLectivo)
class AnioLectivoAdmin(admin.ModelAdmin):
    list_display = ["anio", "fecha_inicio", "fecha_fin", "activo"]
    inlines = [PeriodoInline]


class GradoInline(admin.TabularInline):
    model = Grado
    extra = 0


@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ["nombre", "orden"]
    inlines = [GradoInline]


@admin.register(Seccion)
class SeccionAdmin(admin.ModelAdmin):
    list_display = ["grado", "nombre", "turno", "anio_lectivo", "tutor", "vacantes"]
    list_filter = ["anio_lectivo", "grado__nivel", "turno"]
    autocomplete_fields = ["tutor"]


admin.site.register(Grado)
