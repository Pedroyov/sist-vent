from django.contrib import admin

from .models import Config, Reserva


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "hora", "nombre", "personas", "mesa", "estado")
    list_filter = ("estado", "fecha")
    search_fields = ("nombre", "telefono")


admin.site.register(Config)
