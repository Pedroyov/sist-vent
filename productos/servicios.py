"""Operaciones de stock. Toda entrada o salida pasa por aquí (también las ventas, cuando existan)."""
from decimal import Decimal

from django.db import transaction

from .models import CERO, MovimientoStock, Variante

T = MovimientoStock.Tipo


def mover_stock(variante, cantidad, tipo, usuario=None, nota="", costo_unitario=None, referencia=""):
    """Suma (o resta, si es negativa) la cantidad al stock y lo anota en el kardex.
    El stock puede quedar negativo: es mejor dejar vender y corregir con un conteo que trabar la caja."""
    cantidad = Decimal(cantidad)
    with transaction.atomic():
        v = Variante.objects.select_for_update().get(pk=variante.pk)
        v.stock += cantidad
        campos = ["stock"]
        if costo_unitario is not None and tipo in (T.INGRESO, T.INICIAL):
            v.costo = costo_unitario  # último costo de compra
            campos.append("costo")
        v.save(update_fields=campos)
        mov = MovimientoStock.objects.create(
            variante=v, tipo=tipo, cantidad=cantidad, saldo=v.stock, costo_unitario=costo_unitario,
            nota=nota[:200], referencia=referencia[:60], usuario=usuario,
        )
    variante.stock = v.stock
    if "costo" in campos:
        variante.costo = v.costo
    return mov


def ajustar_a(variante, conteo, usuario=None, nota=""):
    """Deja el stock igual al conteo físico. Devuelve el movimiento o None si ya coincidía."""
    with transaction.atomic():
        v = Variante.objects.select_for_update().get(pk=variante.pk)
        diferencia = Decimal(conteo) - v.stock
        if diferencia == 0:
            return None
        return mover_stock(v, diferencia, T.AJUSTE, usuario, nota or "Conteo de inventario")


def separar(texto):
    """'S, M ,L' -> ['S', 'M', 'L'] sin repetidos ni vacíos."""
    vistos, salida = set(), []
    for parte in (texto or "").replace(";", ",").split(","):
        p = " ".join(parte.split())
        if p and p.lower() not in vistos:
            vistos.add(p.lower())
            salida.append(p)
    return salida


def generar_variantes(producto, opciones1, opciones2=None):
    """Crea las combinaciones (S/Rojo, S/Azul, M/Rojo…). Devuelve (creadas, ya_existían).
    La variante sin nombre del producto se retira (si no tiene stock), porque desde ahora se vende por variante."""
    a, b = separar(opciones1), separar(opciones2)
    nombres = [f"{x} / {y}" for x in a for y in b] if b else a
    if not nombres:
        return 0, 0
    with transaction.atomic():
        unica = producto.variante_unica()
        if unica:
            if unica.stock != CERO:
                raise ValueError("El producto todavía tiene stock sin talla/opción. Ajusta ese stock a 0 antes de crear variantes.")
            from mesas.models import ItemCuenta

            if unica.movimientos.exists() or unica.ventas.exists() or ItemCuenta.objects.filter(variante=unica).exists():
                unica.activa = False
                unica.codigo = ""
                unica.save(update_fields=["activa", "codigo"])
                unica.nombre = f"(sin variante {unica.pk})"
                unica.save(update_fields=["nombre"])
            else:
                unica.delete()
        orden = (producto.variantes.order_by("-orden").values_list("orden", flat=True).first() or 0) + 1
        existentes = {n.lower() for n in producto.variantes.values_list("nombre", flat=True)}
        creadas = 0
        for n in nombres:
            if n.lower() in existentes:
                continue
            Variante.objects.create(producto=producto, nombre=n, orden=orden)
            orden += 1
            creadas += 1
    return creadas, len(nombres) - creadas


def asegurar_variante_unica(producto):
    """Un producto sin variantes con nombre necesita su variante sin nombre para vender y contar stock."""
    if not producto.variantes.filter(activa=True).exists():
        v = producto.variante_unica()
        if v:
            v.activa = True
            v.save(update_fields=["activa"])
            return v
        return Variante.objects.create(producto=producto, nombre="")
    return producto.variante_unica()


# --- Opciones al pedir y agotados ---------------------------------------------------

class OpcionInvalida(Exception):
    pass


def resolver_opciones(producto, ids, revisar_disponible=True):
    """Valida las opciones elegidas para un producto. Devuelve (foto, precio_extra, texto):
    foto = [{"id", "g", "n", "p"}] tal como se guarda en la venta o el pedido."""
    from .models import GrupoOpciones, Opcion

    try:
        ids = sorted({int(i) for i in (ids or [])})
    except (TypeError, ValueError):
        raise OpcionInvalida("Opción no válida.")
    grupos = ordenar_grupos(producto.grupos.filter(activo=True).prefetch_related("opciones"))
    validas = {o.pk: o for g in grupos for o in g.opciones.all() if o.activa}
    elegidas = []
    for i in ids:
        o = validas.get(i)
        if o is None:
            raise OpcionInvalida(f"Una de las opciones ya no está disponible para {producto.nombre}. Recarga la página.")
        if revisar_disponible and o.agotada:
            raise OpcionInvalida(f"«{o.nombre}» está agotado hoy.")
        elegidas.append(o)
    for g in grupos:
        n = sum(1 for o in elegidas if o.grupo_id == g.pk)
        if n < g.minimo:
            raise OpcionInvalida(f"{producto.nombre}: elige {g.nombre.lower()}.")
        if g.maximo and n > g.maximo:
            raise OpcionInvalida(f"{producto.nombre}: en {g.nombre.lower()} se puede elegir hasta {g.maximo}.")
    orden = {g.pk: i for i, g in enumerate(grupos)}
    elegidas.sort(key=lambda o: (orden[o.grupo_id], o.orden, o.pk))
    foto = [{"id": o.pk, "g": o.grupo.nombre, "n": o.nombre, "p": str(o.precio)} for o in elegidas]
    return foto, sum((o.precio for o in elegidas), Decimal("0")), texto_opciones(foto)


def ordenar_grupos(grupos):
    """Primero lo obligatorio (término, acompañamiento) y luego lo opcional (adicionales, cremas)."""
    return sorted(grupos, key=lambda g: (0 if g.minimo else 1, g.orden, g.nombre))


def texto_opciones(foto):
    return ", ".join(o["n"] + (f" +{Decimal(o['p']):.2f}" if Decimal(o.get("p") or 0) else "") for o in foto or [])


def descripcion_con_opciones(nombre, foto):
    t = ", ".join(o["n"] for o in foto or [])
    return f"{nombre} ({t})" if t else nombre


def marcar_agotado(objeto, agotado=True):
    """Producto u opción: agotado por hoy (o disponible de nuevo)."""
    from django.utils import timezone

    campo = "agotado_en" if hasattr(objeto, "agotado_en") else "agotada_en"
    setattr(objeto, campo, timezone.now() if agotado else None)
    objeto.save(update_fields=[campo])
