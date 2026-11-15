"""Señales de ventas para que otros módulos reaccionen sin que ventas dependa de ellos."""
from django.dispatch import Signal

# Se envía dentro de la transacción de anular_venta: venta, usuario, motivo.
venta_anulada = Signal()
