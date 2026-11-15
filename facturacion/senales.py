"""Si se anula una venta con boleta o factura, se emite su nota de crédito (sin que ventas sepa de facturación)."""
from django.db import transaction
from django.dispatch import receiver

from ventas.senales import venta_anulada


@receiver(venta_anulada)
def anular_comprobantes(sender, venta, usuario, motivo, **kwargs):
    from .servicios import anular_por_venta, enviar_seguro

    notas = anular_por_venta(venta, usuario, motivo)
    for n in notas:
        transaction.on_commit(lambda n=n: enviar_seguro(n))
    venta.notas_credito = notas
