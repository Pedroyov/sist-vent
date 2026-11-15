from django.apps import AppConfig


class FacturacionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "facturacion"
    verbose_name = "Facturación electrónica"

    def ready(self):
        from . import senales  # noqa: F401  (al anular una venta, su comprobante se anula con nota de crédito)
