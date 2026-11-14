from django.contrib import admin

from .models import HorarioTrabajador, Trabajador


class HorarioInline(admin.TabularInline):
    model = HorarioTrabajador
    extra = 0


@admin.register(Trabajador)
class TrabajadorAdmin(admin.ModelAdmin):
    list_display = ["apellidos", "nombres", "cargo", "modalidad", "sueldo", "pago_hora", "activo"]
    list_filter = ["cargo", "modalidad", "activo"]
    search_fields = ["apellidos", "nombres", "numero_documento"]
    inlines = [HorarioInline]
