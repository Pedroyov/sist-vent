from django import template

register = template.Library()


@register.filter
def nombre(usuario, defecto="—"):
    """Nombre completo de un usuario, o su usuario, o el texto por defecto si no hay."""
    if not usuario:
        return defecto
    return usuario.get_full_name() or usuario.username


@register.filter
def soles(valor):
    """S/ 1,234.50 — monto con separador de miles."""
    from decimal import Decimal, InvalidOperation

    if valor is None or valor == "":
        return "S/ 0.00"
    try:
        return f"S/ {Decimal(valor):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return f"S/ {valor}"


@register.filter
def costo(valor):
    """Costo unitario: 3.5000 -> 3.50 ; 0.0125 -> 0.0125 (dos decimales salvo que haga falta más)."""
    from decimal import Decimal, InvalidOperation

    if valor is None or valor == "":
        return ""
    try:
        d = Decimal(valor)
    except (InvalidOperation, TypeError, ValueError):
        return valor
    return f"{d:.2f}" if d == d.quantize(Decimal("0.01")) else f"{d.normalize():f}"


@register.filter
def cantidad(valor):
    """3.000 -> 3 ; 1.500 -> 1.5 (stock y cantidades sin ceros de más)."""
    from decimal import Decimal, InvalidOperation

    if valor is None or valor == "":
        return ""
    try:
        d = Decimal(valor).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return valor
    return f"{d:f}"


@register.filter
def hace(fecha):
    """Tiempo transcurrido corto: "8 min", "1 h 05"."""
    from django.utils import timezone

    if not fecha:
        return ""
    minutos = max(0, int((timezone.now() - fecha).total_seconds() // 60))
    if minutos < 60:
        return f"{minutos} min"
    return f"{minutos // 60} h {minutos % 60:02d}"


@register.filter
def wa_enlace(telefono, texto=""):
    """{{ c.telefono|wa_enlace }} → enlace para abrir el chat (vacío si el número no sirve)."""
    from core.utils import enlace_whatsapp

    return enlace_whatsapp(telefono or "", texto)


@register.filter
def whatsapp(telefono):
    """Número para enlaces wa.me (agrega el 51 a los celulares peruanos)."""
    from core.utils import numero_whatsapp

    return numero_whatsapp(telefono)
