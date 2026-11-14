from django.contrib import admin

from .models import Categoria, MovimientoStock, Producto, Variante


class VarianteInline(admin.TabularInline):
    model = Variante
    extra = 0
    readonly_fields = ["stock"]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo", "categoria", "precio", "maneja_stock", "activo"]
    list_filter = ["tipo", "categoria", "activo"]
    search_fields = ["nombre", "variantes__codigo"]
    inlines = [VarianteInline]


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ["fecha", "variante", "tipo", "cantidad", "saldo", "usuario"]
    list_filter = ["tipo"]
    search_fields = ["variante__producto__nombre", "variante__codigo", "referencia"]


admin.site.register(Categoria)
