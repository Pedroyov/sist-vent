"""Cambiar precios en bloque: subir o bajar un %, sumar soles o poner un margen sobre el costo, a una categoría, a lo
que se le compra a un proveedor o a todo, con redondeo. Primero se ve cómo quedaría; luego se aplica y se puede deshacer.
Es la única puerta para cambiar muchos precios a la vez (no tocar `Producto.precio` en lote en otro lado)."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import CambioPrecios, CambioPreciosItem, Producto, Variante

CERO = Decimal("0")
MODOS = (
    ("POR", "Subir o bajar un %"),
    ("MON", "Sumar o restar soles"),
    ("MAR", "Ganar un % sobre el costo"),
)
REDONDEOS = (
    ("", "Sin redondear"),
    ("0.10", "A 10 céntimos (S/ 4.30)"),
    ("0.50", "A 50 céntimos (S/ 4.50)"),
    ("1", "Al sol (S/ 5.00)"),
)


class PreciosError(Exception):
    pass


def leer(datos):
    """Los filtros y la regla tal como llegan del formulario, ya validados."""
    modo = datos.get("modo") if datos.get("modo") in dict(MODOS) else "POR"
    red = datos.get("red") if datos.get("red") in dict(REDONDEOS) else ""
    try:
        valor = Decimal(str(datos.get("valor", "")).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        valor = None
    if valor is not None and (abs(valor) > Decimal("10000") or (modo == "POR" and valor <= -100) or (modo == "MAR" and valor < 0)):
        valor = None
    from core.utils import entero

    return {"modo": modo, "valor": valor, "red": red, "cat": entero(datos.get("cat")), "prov": entero(datos.get("prov")),
            "q": str(datos.get("q", "")).strip()[:60], "tipo": datos.get("tipo") if datos.get("tipo") in ("P", "S") else ""}


def calcular(precio, costo, r):
    """El precio nuevo con la regla `r` (o None si no se puede: margen sin costo)."""
    modo, valor = r["modo"], r["valor"]
    if modo == "POR":
        nuevo = precio * (1 + valor / 100)
    elif modo == "MON":
        nuevo = precio + valor
    else:
        if costo is None or costo <= 0:
            return None
        nuevo = costo * (1 + valor / 100)
    if r["red"]:  # hacia arriba, como se redondea en el mostrador
        paso = Decimal(r["red"])
        nuevo = (nuevo / paso).to_integral_value(ROUND_CEILING) * paso
    return max(CERO, nuevo.quantize(Decimal("0.01"), ROUND_HALF_UP))


def productos(r):
    qs = Producto.objects.filter(activo=True).select_related("categoria").prefetch_related("variantes").order_by("categoria__orden", "categoria__nombre", "nombre")
    if r["cat"]:
        qs = qs.filter(categoria_id=r["cat"])
    if r["tipo"]:
        qs = qs.filter(tipo=r["tipo"])
    for palabra in r["q"].split():
        qs = qs.filter(nombre__icontains=palabra)
    if r["prov"]:  # lo que se le compra a ese proveedor
        from compras.models import CompraItem

        ids = CompraItem.objects.filter(compra__proveedor_id=r["prov"], compra__anulada=False).values("variante__producto_id")
        qs = qs.filter(pk__in=ids)
    return qs


def propuesta(r):
    """Cómo quedarían los precios: [{"clave", "nombre", "categoria", "antes", "despues", "costo", "bajo_costo"}].
    Una fila por producto y otra por cada variante con precio propio. Lo que no cambia no sale."""
    if r["valor"] is None:
        return []
    filas = []
    for p in productos(r):
        variantes = list(p.variantes.all())
        propias = [v for v in variantes if v.precio is not None]
        candidatos = []
        if len(propias) < len(variantes) or not variantes:  # alguna variante usa el precio del producto
            candidatos.append((f"p{p.pk}", p, None, p.nombre, p.precio, p.costo))
        for v in propias:
            candidatos.append((f"v{v.pk}", p, v, f"{p.nombre} · {v.nombre or 'única'}", v.precio, v.costo if v.costo is not None else p.costo))
        for clave, prod, var, nombre, antes, costo in candidatos:
            despues = calcular(antes, costo, r)
            if despues is None or despues == antes:
                continue
            filas.append({"clave": clave, "producto": prod, "variante": var, "nombre": nombre, "antes": antes, "despues": despues,
                          "costo": costo, "categoria": prod.categoria.nombre if prod.categoria_id else "Sin categoría",
                          "bajo_costo": costo is not None and despues < costo})
    return filas


def describir(r, n):
    reglas = {"POR": f"{'+' if r['valor'] >= 0 else ''}{r['valor']:g} %", "MON": f"{'+' if r['valor'] >= 0 else '−'}S/ {abs(r['valor']):.2f}",
              "MAR": f"{r['valor']:g} % sobre el costo"}
    partes = [reglas[r["modo"]]]
    if r["cat"]:
        from .models import Categoria

        c = Categoria.objects.filter(pk=r["cat"]).first()
        partes.append(c.nombre if c else "categoría")
    if r["prov"]:
        from compras.models import Proveedor

        pv = Proveedor.objects.filter(pk=r["prov"]).first()
        partes.append(f"proveedor {pv.nombre}" if pv else "proveedor")
    if r["q"]:
        partes.append(f"«{r['q']}»")
    if r["red"]:
        partes.append(f"redondeo a {r['red']}")
    return f"{' · '.join(partes)} ({n} precio{'s' if n != 1 else ''})"[:200]


def aplicar(r, claves, usuario):
    """Aplica la regla solo a las filas elegidas. Los precios se calculan de nuevo aquí (no se confía en lo que manda la
    pantalla). Guarda el antes y el después para poder deshacer, y lo anota en la bitácora."""
    from core.bitacora import anotar

    claves = set(claves)
    filas = [f for f in propuesta(r) if f["clave"] in claves]
    if not filas:
        raise PreciosError("No hay precios para cambiar.")
    with transaction.atomic():
        cambio = CambioPrecios.objects.create(usuario=usuario, descripcion=describir(r, len(filas)))
        items = []
        for f in filas:
            if f["variante"] is None:
                Producto.objects.filter(pk=f["producto"].pk).update(precio=f["despues"])
            else:
                Variante.objects.filter(pk=f["variante"].pk).update(precio=f["despues"])
            items.append(CambioPreciosItem(cambio=cambio, producto=f["producto"], variante=f["variante"], antes=f["antes"], despues=f["despues"]))
        CambioPreciosItem.objects.bulk_create(items)
        anotar("producto.precios_bloque", f"Cambio de precios en bloque: {cambio.descripcion}", objeto=cambio, usuario=usuario)
    return cambio


def deshacer(cambio, usuario):
    """Vuelve cada precio a como estaba, salvo los que alguien cambió después (esos se dejan). Devuelve (vueltos, dejados)."""
    from core.bitacora import anotar

    if cambio.deshecho:
        raise PreciosError("Ese cambio ya se deshizo.")
    vueltos = dejados = 0
    with transaction.atomic():
        for i in cambio.items.select_related("producto", "variante"):
            actual = i.variante.precio if i.variante_id else i.producto.precio
            if actual != i.despues:
                dejados += 1
                continue
            if i.variante_id:
                Variante.objects.filter(pk=i.variante_id).update(precio=i.antes)
            else:
                Producto.objects.filter(pk=i.producto_id).update(precio=i.antes)
            vueltos += 1
        cambio.deshecho, cambio.deshecho_por = timezone.now(), usuario
        cambio.save(update_fields=["deshecho", "deshecho_por"])
        anotar("producto.precios_bloque", f"Se deshizo el cambio de precios «{cambio.descripcion}»: {vueltos} volvieron"
               + (f", {dejados} se dejaron porque los cambiaron después" if dejados else ""), objeto=cambio, usuario=usuario)
    return vueltos, dejados


def aplicar_precios(nuevos, usuario, descripcion):
    """Pone precios elegidos a mano a unas variantes ([(variante, precio)]): la que tiene precio propio cambia ella; la
    que usa el del producto cambia el del producto. Queda en el historial para deshacer, igual que un cambio en bloque."""
    from core.bitacora import anotar

    items, hechos = [], set()
    with transaction.atomic():
        cambio = CambioPrecios.objects.create(usuario=usuario, descripcion="")
        for v, precio in nuevos:
            precio = Decimal(precio).quantize(Decimal("0.01"))
            if precio <= 0:
                raise PreciosError(f"El precio de {v} debe ser mayor que cero.")
            if v.precio is not None:
                clave, antes = ("v", v.pk), v.precio
                Variante.objects.filter(pk=v.pk).update(precio=precio)
                var = v
            else:
                clave, antes = ("p", v.producto_id), v.producto.precio
                Producto.objects.filter(pk=v.producto_id).update(precio=precio)
                var = None
            if clave in hechos or antes == precio:
                continue
            hechos.add(clave)
            items.append(CambioPreciosItem(cambio=cambio, producto_id=v.producto_id, variante=var, antes=antes, despues=precio))
        if not items:
            raise PreciosError("No hay precios para cambiar.")
        CambioPreciosItem.objects.bulk_create(items)
        cambio.descripcion = f"{descripcion} ({len(items)} precio{'s' if len(items) != 1 else ''})"[:200]
        cambio.save(update_fields=["descripcion"])
        anotar("producto.precios_bloque", f"Cambio de precios: {cambio.descripcion}", objeto=cambio, usuario=usuario)
    return cambio
