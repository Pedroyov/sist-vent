from django.contrib import admin

from .models import Pago, Venta, VentaItem


class ItemInline(admin.TabularInline):
    model = VentaItem
    extra = 0
    raw_id_fields = ["variante"]


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ["numero", "fecha", "estado", "total", "usuario", "cliente_nombre"]
    list_filter = ["estado", "usuario"]
    search_fields = ["numero", "cliente_nombre", "cliente_documento"]
    inlines = [ItemInline, PagoInline]
