from django.contrib import admin

from .models import Cuenta, ItemCuenta, Mesa, Zona


class ItemInline(admin.TabularInline):
    model = ItemCuenta
    extra = 0
    raw_id_fields = ["variante", "venta"]


@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = ["id", "mesa", "nombre", "mozo", "estado", "abierta_en"]
    list_filter = ["estado"]
    inlines = [ItemInline]


admin.site.register(Zona)
admin.site.register(Mesa)
