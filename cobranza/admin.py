from django.contrib import admin

from .models import Cargo, ConfigCobranza, Concepto, Descuento, Pago, PagoDetalle


@admin.register(ConfigCobranza)
class ConfigCobranzaAdmin(admin.ModelAdmin):
    list_display = ["anio_lectivo", "monto_matricula", "monto_pension", "mes_inicio", "mes_fin", "mora_activa"]


@admin.register(Concepto)
class ConceptoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "anio_lectivo", "tipo", "monto", "vencimiento", "automatico"]
    list_filter = ["anio_lectivo", "tipo"]


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ["alumno", "concepto", "monto", "descuento", "pagado", "vencimiento", "anulado"]
    list_filter = ["concepto__anio_lectivo", "concepto", "anulado"]
    search_fields = ["alumno__numero_documento", "alumno__apellido_paterno", "alumno__nombres"]
    readonly_fields = ["pagado"]


@admin.register(Descuento)
class DescuentoAdmin(admin.ModelAdmin):
    list_display = ["alumno", "anio_lectivo", "motivo", "tipo", "valor"]


class DetalleInline(admin.TabularInline):
    model = PagoDetalle
    extra = 0
    readonly_fields = ["cargo", "monto", "mora"]
    can_delete = False


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["numero_texto", "fecha", "alumno", "total", "metodo", "anulado"]
    list_filter = ["anio_lectivo", "metodo", "anulado"]
    search_fields = ["alumno__numero_documento", "alumno__apellido_paterno", "numero_operacion"]
    inlines = [DetalleInline]
    readonly_fields = ["total", "anulado", "anulado_por", "anulado_en"]
