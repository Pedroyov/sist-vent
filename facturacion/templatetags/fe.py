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
    if not texto:
        return ""
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    svg = svg[svg.index("<svg"):].replace("<svg ", f'<svg width="{tam}" height="{tam}" ', 1)
    return mark_safe(svg)


@register.simple_tag
def comprobante_de(venta):
    """La boleta o factura vigente de una venta (la primera no rechazada), o None."""
    return venta.comprobantes.exclude(tipo="07").exclude(estado="REC").first()
