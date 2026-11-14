"""Registrar y anular ventas. Aquí se valida todo lo que llega del punto de venta: el navegador no es de fiar."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from productos.models import MovimientoStock, Variante
from productos.servicios import mover_stock

from .models import CERO, Correlativo, MetodoPago, Pago, Venta, VentaItem

CENT = Decimal("0.01")


class VentaInvalida(Exception):
    pass


def _dec(valor, campo, minimo=CERO):
    try:
        d = Decimal(str(valor).strip())
    except (InvalidOperation, AttributeError):
        raise VentaInvalida(f"{campo}: no es un número válido.")
    if not d.is_finite() or d < minimo:
        raise VentaInvalida(f"{campo}: valor no permitido.")
    return d


def dinero(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def registrar_venta(usuario, items, pagos, descuento=0, cliente_nombre="", cliente_documento="", nota="",
                    token=None, puede_cambiar_precio=False):
    """items: [{"variante": id, "cantidad": "2", "precio": "3.50"}]; pagos: [{"metodo": "EFE", "monto": "20"}].
    El monto de efectivo es lo que entregó el cliente: el vuelto sale de ahí."""
    if token:
        previa = Venta.objects.filter(token=token).first()
        if previa:
            return previa
    if not items:
        raise VentaInvalida("No hay productos en la venta.")
    if len(items) > 300:
        raise VentaInvalida("Demasiados productos en una sola venta.")

    ids = []
    for it in items:
        try:
            ids.append(int(it["variante"]))
        except (KeyError, TypeError, ValueError):
            raise VentaInvalida("Producto no válido.")
    variantes = Variante.objects.select_related("producto").in_bulk(ids)

    lineas, subtotal = [], CERO
    for it, vid in zip(items, ids):
        v = variantes.get(vid)
        if v is None or not v.activa or not v.producto.activo:
            raise VentaInvalida("Uno de los productos ya no está disponible. Recarga la página.")
        nombre = v.nombre_completo
        cantidad = _dec(it.get("cantidad"), f"Cantidad de {nombre}")
        if cantidad <= 0:
            raise VentaInvalida(f"La cantidad de {nombre} debe ser mayor que cero.")
        if not v.producto.fraccionable and cantidad != cantidad.to_integral_value():
            raise VentaInvalida(f"{nombre} se vende por unidades enteras.")
        lista = v.precio_venta
        precio = lista
        if puede_cambiar_precio and it.get("precio") not in (None, ""):
            precio = dinero(_dec(it["precio"], f"Precio de {nombre}"))
        importe = dinero(precio * cantidad)
        lineas.append((v, cantidad, precio, lista, importe))
        subtotal += importe

    descuento = dinero(_dec(descuento or 0, "Descuento"))
    if descuento and not puede_cambiar_precio:
        raise VentaInvalida("No tienes permiso para dar descuentos.")
    if descuento > subtotal:
        raise VentaInvalida("El descuento no puede ser mayor que el total.")
    total = subtotal - descuento

    # Pagos: se juntan por método. El vuelto solo puede salir del efectivo.
    por_metodo = {}
    for p in pagos or []:
        metodo = p.get("metodo")
        if metodo not in MetodoPago.values:
            raise VentaInvalida("Método de pago no válido.")
        monto = dinero(_dec(p.get("monto") or 0, "Monto"))
        if monto > 0:
            m = por_metodo.setdefault(metodo, {"monto": CERO, "referencia": ""})
            m["monto"] += monto
            m["referencia"] = (m["referencia"] or str(p.get("referencia") or "").strip())[:60]
    pagado = sum((m["monto"] for m in por_metodo.values()), CERO)
    if pagado < total:
        raise VentaInvalida(f"Falta cobrar S/ {total - pagado:.2f}.")
    vuelto = pagado - total
    efectivo = por_metodo.get(MetodoPago.EFECTIVO, {}).get("monto", CERO)
    if vuelto > efectivo:
        raise VentaInvalida("Con Yape, Plin, tarjeta o transferencia se cobra el monto exacto: el vuelto solo sale del efectivo.")

    try:
        with transaction.atomic():
            venta = Venta.objects.create(
                numero=Correlativo.siguiente("venta"), usuario=usuario, subtotal=subtotal, descuento=descuento,
                total=total, recibido=efectivo if efectivo else None, vuelto=vuelto, token=token or None,
                cliente_nombre=" ".join(str(cliente_nombre or "").split())[:150],
                cliente_documento="".join(c for c in str(cliente_documento or "") if c.isalnum())[:11],
                nota=str(nota or "").strip()[:200],
            )
            for v, cantidad, precio, lista, importe in lineas:
                VentaItem.objects.create(venta=venta, variante=v, descripcion=v.nombre_completo[:240], cantidad=cantidad,
                                         precio_unitario=precio, precio_lista=lista, costo_unitario=v.costo_efectivo,
                                         subtotal=importe)
                if v.producto.maneja_stock:
                    mover_stock(v, -cantidad, MovimientoStock.Tipo.VENTA, usuario, referencia=f"Venta {venta.numero_str}")
            for metodo, m in por_metodo.items():
                monto = m["monto"] - (vuelto if metodo == MetodoPago.EFECTIVO else CERO)
                if monto > 0:
                    Pago.objects.create(venta=venta, metodo=metodo, monto=monto, referencia=m["referencia"])
    except IntegrityError:
        if token:  # doble clic: la otra petición ya la registró
            previa = Venta.objects.filter(token=token).first()
            if previa:
                return previa
        raise
    return venta


def anular_venta(venta, usuario, motivo):
    """Anula la venta y devuelve al stock lo vendido. Los datos no se borran."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise VentaInvalida("Indica el motivo de la anulación.")
    with transaction.atomic():
        v = Venta.objects.select_for_update().get(pk=venta.pk)
        if v.anulada:
            raise VentaInvalida("Esta venta ya estaba anulada.")
        for item in v.items.select_related("variante__producto"):
            if item.variante.producto.maneja_stock:
                mover_stock(item.variante, item.cantidad, MovimientoStock.Tipo.DEVOLUCION, usuario,
                            nota=f"Anulación: {motivo}", referencia=f"Venta {v.numero_str}")
        v.estado = Venta.Estado.ANULADA
        v.anulada_en = timezone.now()
        v.anulada_por = usuario
        v.motivo_anulacion = motivo
        v.save(update_fields=["estado", "anulada_en", "anulada_por", "motivo_anulacion"])
    return v


def resumen(ventas):
    """Totales de un conjunto de ventas pagadas: total, cantidad, ticket promedio, por método, costo."""
    from django.db.models import Count, Sum

    pagadas = ventas.filter(estado=Venta.Estado.PAGADA)
    t = pagadas.aggregate(total=Sum("total"), n=Count("id"), descuentos=Sum("descuento"))
    total, n = t["total"] or CERO, t["n"] or 0
    metodos = (Pago.objects.filter(venta__in=pagadas).values("metodo").annotate(total=Sum("monto"), n=Count("venta", distinct=True))
               .order_by("-total"))
    nombres = dict(MetodoPago.choices)
    costo = CERO
    for i in VentaItem.objects.filter(venta__in=pagadas, costo_unitario__isnull=False).values("cantidad", "costo_unitario"):
        costo += i["cantidad"] * i["costo_unitario"]
    sin_costo = VentaItem.objects.filter(venta__in=pagadas, costo_unitario__isnull=True).exists()
    return {
        "total": total, "n": n, "promedio": dinero(total / n) if n else CERO, "descuentos": t["descuentos"] or CERO,
        "metodos": [{"metodo": nombres.get(m["metodo"], m["metodo"]), "codigo": m["metodo"], "total": m["total"], "n": m["n"]} for m in metodos],
        "ganancia": total - dinero(costo), "sin_costo": sin_costo,
        "anuladas": ventas.filter(estado=Venta.Estado.ANULADA).count(),
    }
