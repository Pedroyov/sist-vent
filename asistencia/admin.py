from django.contrib import admin

from .models import Asistencia, AvisoFalta, Sesion


class AsistenciaInline(admin.TabularInline):
    model = Asistencia
    extra = 0


@admin.register(Sesion)
class SesionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "seccion", "asignacion", "tomado_por"]
    list_filter = ["fecha", "seccion__anio_lectivo"]
    inlines = [AsistenciaInline]


admin.site.register(AvisoFalta)
