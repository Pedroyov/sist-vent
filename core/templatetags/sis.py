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
