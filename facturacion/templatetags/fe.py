from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def config_fe():
    """La configuración de facturación si el módulo está activo; si no, None."""
    from facturacion.servicios import activo

    if not activo():
        return None
    from facturacion.models import Config

    return Config.cargar()


@register.filter
def qr_svg(texto, tam=110):
    """Código QR en SVG (se imprime nítido en la ticketera)."""
    from core.utils import qr_svg as qr

    return qr(texto, tam)


@register.simple_tag
def comprobante_de(venta):
    """La boleta o factura vigente de una venta (la primera no rechazada), o None."""
    return venta.comprobantes.exclude(tipo="07").exclude(estado="REC").first()
