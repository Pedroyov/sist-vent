"""Promociones (función «Promociones»): el único lugar donde se decide qué promoción le toca a cada línea de una venta.

- Entran las líneas sin cortesía y sin precio cambiado a mano. La promoción se calcula sobre el precio normal: si la
  línea ya tenía un precio especial (listas de precios), se queda con lo que salga más barato. Las rebajas no se suman.
- Cada promoción mira sus productos y categorías y si vale a la hora de la línea (en mesas, la hora en que se pidió).
- Si una línea entra en dos promociones, gana la que más rebaja; luego la siguiente con las líneas que quedan.
- 2×1 / 3×2 junta todas sus líneas (tallas, sabores, productos de la categoría) y regala las unidades más baratas.
"""
from decimal import ROUND_HALF_UP, Decimal

CERO = Decimal("0")
CENT = Decimal("0.01")


def _r(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def activa():
    from core.models import Ajustes

    return Ajustes.cargar().usa_promociones


def vigentes(momento=None):
    """Las promociones activas que valen ahora (para mostrarlas)."""
    from .models import Promocion

    return [p for p in Promocion.objects.filter(activa=True) if p.vigente(momento)]


def _apta(linea):
    return not linea["cortesia"] and linea["precio"] == linea["lista"] and linea["importe"] > 0


def _normal(linea):
    """Precio sin la lista de precios (sobre ese se calcula la promoción)."""
    return linea.get("normal", linea["precio"])


def _rebajas(promo, lineas, indices):
    """{índice: rebaja} de una promoción sobre esas líneas."""
    from .models import Promocion

    salida = {}
    if promo.tipo == Promocion.Tipo.PORCENTAJE and promo.porcentaje:
        for i in indices:
            salida[i] = _r(_normal(lineas[i]) * lineas[i]["cantidad"] * promo.porcentaje / Decimal("100"))
    elif promo.tipo == Promocion.Tipo.PRECIO and promo.precio is not None:
        for i in indices:
            l = lineas[i]
            if promo.precio < _normal(l):
                salida[i] = _r((_normal(l) - promo.precio) * l["cantidad"])
    elif promo.tipo == Promocion.Tipo.NXM and promo.lleva and promo.paga is not None and promo.lleva > promo.paga:
        unidades = sorted((_normal(lineas[i]), i) for i in indices for _ in range(int(lineas[i]["cantidad"])))
        gratis = len(unidades) // promo.lleva * (promo.lleva - promo.paga)
        for precio, i in unidades[:gratis]:
            salida[i] = salida.get(i, CERO) + precio
    return {i: r for i, r in salida.items() if r > 0}


def _con_promo(linea, rebaja):
    """Lo que pagaría la línea con la promoción (a precio normal menos la rebaja)."""
    return max(CERO, _r(_normal(linea) * linea["cantidad"]) - rebaja)


def aplicar(lineas):
    """Pone en cada línea su promoción (`promo`, `promo_desc`) y le resta la rebaja al importe."""
    if not lineas or not activa():
        return
    from .models import Promocion

    promos = list(Promocion.objects.filter(activa=True).prefetch_related("productos", "categorias"))
    if not promos:
        return
    candidatas = []
    for p in promos:
        productos = {x.pk for x in p.productos.all()}
        categorias = {x.pk for x in p.categorias.all()}
        indices = [i for i, l in enumerate(lineas) if _apta(l) and (l["v"].producto_id in productos or l["v"].producto.categoria_id in categorias)
                   and p.vigente(l.get("momento"))]
        if indices:
            candidatas.append((p, indices))
    tomadas = set()
    while candidatas:
        mejor = None
        for p, indices in candidatas:
            libres = [i for i in indices if i not in tomadas]
            r = {i: x for i, x in _rebajas(p, lineas, libres).items() if _con_promo(lineas[i], x) < lineas[i]["importe"]}
            total = sum((lineas[i]["importe"] - _con_promo(lineas[i], x) for i, x in r.items()), CERO)
            if total > 0 and (mejor is None or total > mejor[2]):
                mejor = (p, libres, total, r)
        if mejor is None:
            break
        p, libres, _, r = mejor
        for i, rebaja in r.items():
            l = lineas[i]
            if l["regla"]:  # sale más barato con la promo que con su precio especial: vuelve al precio normal
                l["precio"] = l["lista"] = _normal(l)
                l["regla"] = ""
            rebaja = min(rebaja, _r(l["precio"] * l["cantidad"]))
            l["promo"], l["promo_desc"], l["importe"] = p, rebaja, _r(l["precio"] * l["cantidad"]) - rebaja
        tomadas.update(libres)
        candidatas = [(q, ix) for q, ix in candidatas if q.pk != p.pk]


def resumen(desde, hasta):
    """Por promoción, en ventas vigentes del periodo: en cuántas ventas entró, lo vendido (ya rebajado) y lo rebajado."""
    from django.db.models import Count, Sum

    from core.utils import dias
    from ventas.models import Venta, VentaItem

    filas = (VentaItem.objects.filter(**dias("venta__fecha", desde, hasta), venta__estado=Venta.Estado.PAGADA, promo__isnull=False)
             .values("promo", "promo__nombre").annotate(ventas=Count("venta", distinct=True), vendido=Sum("subtotal"),
                                                        rebajado=Sum("promo_descuento")).order_by("-rebajado"))
    return [{"id": f["promo"], "nombre": f["promo__nombre"], "ventas": f["ventas"], "vendido": _r(f["vendido"] or CERO),
             "rebajado": _r(f["rebajado"] or CERO)} for f in filas]
