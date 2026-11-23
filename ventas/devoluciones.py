"""Devoluciones parciales: el cliente devuelve uno o varios productos de una venta.

La venta no cambia. Por cada línea devuelta se guarda la cantidad, lo que se le devuelve (con su parte del descuento de la
venta) y si vuelve al stock o sale como merma. El dinero se devuelve de la caja abierta de quien devuelve, fuera de caja
(Yape, transferencia) o descontando de la deuda del cliente. Si la venta tuvo boleta o factura, se emite nota de crédito
parcial (motivo SUNAT 07). Reportes cuenta las ventas netas de devoluciones.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import CERO, Devolucion, DevolucionItem, Venta, VentaItem
from .servicios import VentaInvalida

CENTIMO = Decimal("0.01")
DEVOLUCION_DEUDA = "DEV"  # «método» del Abono con que una devolución baja la deuda del fiado (no es dinero que entra)


def devuelto(venta):
    """{id de línea: cantidad ya devuelta}."""
    return {r["item_id"]: r["c"] for r in DevolucionItem.objects.filter(item__venta=venta).values("item_id").annotate(c=Sum("cantidad"))}


def _factor(venta):
    """Parte del precio que de verdad se cobró (el descuento de la venta se reparte entre las líneas)."""
    return (venta.total / venta.subtotal) if venta.subtotal else Decimal("0")


def lineas(venta):
    """Cada línea con lo vendido, lo ya devuelto, lo que aún se puede devolver y el precio unitario neto."""
    ya, f = devuelto(venta), _factor(venta)
    out = []
    for i in venta.items.select_related("variante__producto").order_by("id"):
        queda = i.cantidad - ya.get(i.pk, Decimal("0"))
        unitario = (i.subtotal / i.cantidad * f) if i.cantidad else CERO
        out.append({"item": i, "vendido": i.cantidad, "devuelto": ya.get(i.pk, Decimal("0")), "queda": queda, "unitario": unitario,
                    "servicio": i.variante.producto.es_servicio, "fraccion": i.variante.producto.unidad in ("KG", "LT", "MT")})
    return out


def devuelto_total(venta):
    return venta.devoluciones.aggregate(t=Sum("total"))["t"] or CERO


def por_que_no(venta):
    """"" si a esta venta todavía se le puede devolver algo; si no, el motivo."""
    from core.models import Ajustes

    if venta.anulada:
        return "La venta está anulada."
    dias = Ajustes.cargar().dias_devolucion
    if timezone.localdate() - timezone.localtime(venta.fecha).date() > timedelta(days=dias):
        return f"Pasaron más de {dias} días desde la venta (Datos del negocio → días para devolver)."
    if all(l["queda"] <= 0 for l in lineas(venta)):
        return "Ya se devolvió todo lo de esta venta."
    return ""


def devolver(venta, pedido, reembolso, usuario, motivo, autorizo=None):
    """`pedido` = [{"item": id, "cantidad": "1", "al_stock": True}]. Devuelve la Devolucion (con su nota de crédito, si toca:
    se envía después de la transacción con facturacion.servicios.enviar_seguro)."""
    from caja.models import MovimientoCaja, SesionCaja
    from core.bitacora import anotar
    from productos.models import MovimientoStock
    from productos.servicios import consumo, mover_stock

    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise VentaInvalida("Indica el motivo de la devolución.")
    if reembolso not in Devolucion.Reembolso.values:
        raise VentaInvalida("Elige cómo se devuelve el dinero.")
    with transaction.atomic():
        v = Venta.objects.select_for_update().get(pk=venta.pk)
        if error := por_que_no(v):
            raise VentaInvalida(error)
        disponibles = {l["item"].pk: l for l in lineas(v)}
        elegidas = []
        for p in pedido or []:
            try:
                item_id, cantidad = int(p.get("item")), Decimal(str(p.get("cantidad") or 0))
            except (TypeError, ValueError, ArithmeticError):
                raise VentaInvalida("Cantidad no válida.")
            if cantidad <= 0:
                continue
            l = disponibles.get(item_id)
            if l is None:
                raise VentaInvalida("Ese producto no es de esta venta.")
            if cantidad > l["queda"]:
                raise VentaInvalida(f"De «{l['item'].descripcion}» solo se pueden devolver {l['queda'].normalize():f}.")
            elegidas.append((l, cantidad, bool(p.get("al_stock", True))))
        if not elegidas:
            raise VentaInvalida("Marca qué productos se devuelven.")
        importes = [(l, c, s, (l["unitario"] * c).quantize(CENTIMO)) for l, c, s in elegidas]
        total = sum((x[3] for x in importes), CERO)
        # si con esto se devuelve todo lo que queda, el total cuadra exacto con lo que faltaba devolver
        pedido_por_linea = {}
        for l, c, _ in elegidas:
            pedido_por_linea[l["item"].pk] = pedido_por_linea.get(l["item"].pk, Decimal("0")) + c
        if any(c > disponibles[k]["queda"] for k, c in pedido_por_linea.items()):
            raise VentaInvalida("Se pidió devolver más de lo que queda.")
        if all(dl["queda"] - pedido_por_linea.get(k, 0) <= 0 for k, dl in disponibles.items()):
            ajuste = (v.total - devuelto_total(v)) - total
            if ajuste and importes:
                l, c, s, imp = importes[-1]
                importes[-1] = (l, c, s, imp + ajuste)
                total += ajuste
        d = Devolucion.objects.create(venta=v, usuario=usuario, autorizo=autorizo if autorizo and autorizo != usuario else None,
                                      motivo=motivo, total=total, reembolso=reembolso)
        for l, cantidad, al_stock, importe in importes:
            i = l["item"]
            DevolucionItem.objects.create(devolucion=d, item=i, cantidad=cantidad, importe=importe, costo_unitario=i.costo_unitario, al_stock=al_stock)
            for vs, q in consumo(i.variante, cantidad, i.opciones):
                mover_stock(vs, q, MovimientoStock.Tipo.DEVOLUCION, usuario, nota=f"Devolución: {motivo}", referencia=f"Venta {v.numero_str}")
                if not al_stock:
                    mover_stock(vs, -q, MovimientoStock.Tipo.SALIDA, usuario, nota=f"Merma por devolución: {motivo}",
                                referencia=f"Venta {v.numero_str}")
        concepto = f"Devolución de la venta {v.numero_str}: {motivo}"[:150]
        if total > 0:
            if reembolso == Devolucion.Reembolso.CAJA:
                from caja.servicios import movimiento

                sesion = SesionCaja.abierta_de(usuario)
                if sesion is None:
                    raise VentaInvalida(f"Para devolver S/ {total:.2f} en efectivo abre tu caja primero: así la salida queda registrada.")
                d.movimiento = movimiento(sesion, MovimientoCaja.Tipo.EGRESO, total, concepto, usuario, MovimientoCaja.Categoria.DEVOLUCION,
                                          automatico=True)
            elif reembolso == Devolucion.Reembolso.FUERA:
                d.movimiento = MovimientoCaja.objects.create(sesion=None, tipo=MovimientoCaja.Tipo.EGRESO, monto=total, concepto=concepto,
                                                             categoria=MovimientoCaja.Categoria.DEVOLUCION, usuario=usuario, automatico=True)
            elif reembolso == Devolucion.Reembolso.SALDO:
                from clientes.models import MovimientoSaldo
                from clientes.saldo import abonar

                if not v.cliente_id:
                    raise VentaInvalida("La venta no tiene cliente: el saldo a favor necesita un cliente.")
                abonar(v.cliente, total, MovimientoSaldo.Tipo.DEVOLUCION, usuario, concepto, venta=v, devolucion=d)
            else:
                from clientes.models import Abono, Cliente

                if not v.cliente_id:
                    raise VentaInvalida("La venta no tiene cliente: elige otra forma de devolver el dinero.")
                cliente = Cliente.objects.select_for_update().get(pk=v.cliente_id)
                if total > cliente.saldo:
                    raise VentaInvalida(f"{cliente.nombre} debe S/ {cliente.saldo:.2f}: no alcanza para descontar S/ {total:.2f}. Elige otra forma.")
                d.abono = Abono.objects.create(cliente=cliente, monto=total, metodo=DEVOLUCION_DEUDA, usuario=usuario, nota=concepto[:200])
            if v.cliente_id and v.total:
                from clientes.saldo import ganado_en, quitar

                quitar(v.cliente_id, ganado_en(v) * total / v.total, usuario, concepto, venta=v, devolucion=d)  # su parte del monedero
        from facturacion.templatetags.fe import comprobante_de

        cp = comprobante_de(v)
        if cp is not None and total > 0:
            from facturacion.servicios import nota_credito_parcial

            d.nota_credito = nota_credito_parcial(cp, [(l["item"], c, imp) for l, c, _, imp in importes], motivo, usuario)
        d.save(update_fields=["movimiento", "abono", "nota_credito"])
        detalle = ", ".join(f"{c.normalize():f} × {l['item'].descripcion}{'' if s else ' (merma)'}" for l, c, s, _ in importes)
        anotar("venta.devolucion", f"Devolución en la venta {v.numero_str} por S/ {total:.2f} ({Devolucion.Reembolso(reembolso).label.lower()}): "
               f"{detalle}. Motivo: {motivo}"[:300], objeto=v, usuario=usuario,
               despues={"total": total, "reembolso": reembolso, "autorizo": str(autorizo or usuario)})
    return d


def en_periodo(desde, hasta):
    """Devoluciones hechas en esos días (cuentan el día que se devolvió, no el de la venta)."""
    from core.utils import dias

    return Devolucion.objects.filter(**dias("fecha", desde, hasta))


def resumen_periodo(desde, hasta):
    """Total devuelto, cuántas y cuánto baja la ganancia (lo devuelto menos el costo de lo que volvió al stock)."""
    items = DevolucionItem.objects.filter(devolucion__in=en_periodo(desde, hasta))
    total = n = CERO
    costo_recuperado = CERO
    for it in items.values("importe", "cantidad", "costo_unitario", "al_stock"):
        total += it["importe"]
        if it["al_stock"] and it["costo_unitario"] is not None:
            costo_recuperado += it["cantidad"] * it["costo_unitario"]
    n = en_periodo(desde, hasta).count()
    return {"total": total.quantize(CENTIMO), "n": n, "ganancia": (total - costo_recuperado).quantize(CENTIMO)}
