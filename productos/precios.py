"""Listas de precios: el único lugar donde se decide qué precio tiene algo al vender (función «Listas de precios»).

Reglas (la pantalla de venta las pide al servidor con ventas:cotizar, así ve lo mismo que se cobrará):
- El precio normal es el de la variante (o el del producto).
- Con un cliente de una lista: el normal menos el % de la lista.
- Los precios especiales del producto (por cantidad, por lista o ambos) valen para las variantes que usan el precio del
  producto, cuando la cantidad de ese producto en la venta (sumando sus variantes) llega a «desde».
- Gana el más bajo. No es un descuento: no pide motivo ni autorización.
"""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def activa():
    from core.models import Ajustes

    return Ajustes.cargar().usa_precios


def con_porcentaje(precio, porcentaje):
    return (precio * (Decimal("100") - porcentaje) / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)


def lista_de(cliente_id):
    """La lista de precios activa del cliente (o None)."""
    if not cliente_id or not activa():
        return None
    from clientes.models import Cliente

    c = Cliente.objects.filter(pk=cliente_id, lista__activa=True).select_related("lista").first()
    return c.lista if c else None


def especiales(producto_ids):
    """{producto_id: [(lista_id|None, desde, precio, nombre_lista)]} de las listas activas."""
    from django.db.models import Q

    from .models import PrecioEspecial

    salida = {}
    for pe in (PrecioEspecial.objects.filter(producto_id__in=list(producto_ids))
               .filter(Q(lista__isnull=True) | Q(lista__activa=True)).select_related("lista")):
        salida.setdefault(pe.producto_id, []).append((pe.lista_id, pe.desde, pe.precio, pe.lista.nombre if pe.lista else ""))
    return salida


def precio(variante, cantidad_producto, lista=None, filas=()):
    """(precio unitario, por qué) para una variante. `filas` = especiales(...)[producto_id]."""
    normal = variante.precio_venta
    mejor, motivo = normal, ""
    if lista is not None and lista.porcentaje:
        p = con_porcentaje(normal, lista.porcentaje)
        if p < mejor:
            mejor, motivo = p, f"Precio {lista.nombre}"
    if variante.precio is None:
        for lista_id, desde, p, nombre in filas:
            if (lista_id is None or (lista is not None and lista_id == lista.pk)) and cantidad_producto >= desde and p < mejor:
                mejor, motivo = p, f"Precio {nombre}" if lista_id else "Precio por cantidad"
    return mejor, motivo
