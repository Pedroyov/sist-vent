from django.contrib import admin

from .models import Config, Cuota, Inscripcion, Pago, PagoCuota, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["nombre", "precio", "frecuencia", "num_cuotas", "matricula", "activo"]


class CuotaInline(admin.TabularInline):
    model = Cuota
    extra = 0


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ["cliente", "alumno", "plan", "precio", "inicio", "estado"]
    list_filter = ["estado", "plan"]
    search_fields = ["cliente__nombre", "alumno"]
    inlines = [CuotaInline]


class PagoCuotaInline(admin.TabularInline):
    model = PagoCuota
    extra = 0


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["id", "cliente", "fecha", "monto", "metodo", "anulado"]
    inlines = [PagoCuotaInline]


admin.site.register(Config)
