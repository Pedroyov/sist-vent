from django.contrib import admin

from .models import Ausencia, Cita, Config, Horario


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "inicio", "nombre", "servicio_nombre", "profesional", "estado")
    list_filter = ("estado", "profesional", "fecha")
    search_fields = ("nombre", "telefono")


admin.site.register(Horario)
admin.site.register(Ausencia)
admin.site.register(Config)
