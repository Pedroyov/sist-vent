from django.contrib import admin

from .models import MovimientoCaja, SesionCaja


class MovimientoInline(admin.TabularInline):
    model = MovimientoCaja
    extra = 0


@admin.register(SesionCaja)
class SesionCajaAdmin(admin.ModelAdmin):
    list_display = ["id", "usuario", "estado", "abierta_en", "cerrada_en", "esperado", "contado", "diferencia"]
    list_filter = ["estado", "usuario"]
    inlines = [MovimientoInline]
