from django.contrib import admin

from .models import Abono, Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo_documento", "numero_documento", "telefono", "limite_credito", "activo"]
    search_fields = ["nombre", "numero_documento"]


@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ["id", "cliente", "fecha", "monto", "metodo", "anulado"]
