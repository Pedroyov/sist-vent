"""Registrar y anular ventas. Aquí se valida todo lo que llega del punto de venta: el navegador no es de fiar."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from productos.models import MovimientoStock, Variante
from productos.servicios import OpcionInvalida, descripcion_con_opciones, mover_stock, resolver_opciones

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
                    token=None, puede_cambiar_precio=False, puede_descontar=None, propina=0, atendio=None, despues=None,
                    desde_pedido=False, cliente_id=None, puede_fiar=False, puede_exceder_limite=False,
                    descuento_motivo="", descuento_por=None):
    """items: [{"variante": id, "cantidad": "2", "precio": "3.50"}]; pagos: [{"metodo": "EFE", "monto": "20"}].
    El monto de efectivo es lo que entregó el cliente: el vuelto sale de ahí.
    `despues(venta)` se ejecuta dentro de la misma transacción (por ejemplo, para marcar la mesa como cobrada)."""
    if puede_descontar is None:
        puede_descontar = puede_cambiar_precio
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
        if v is None or (not desde_pedido and (not v.activa or not v.producto.activo)):
            raise VentaInvalida("Uno de los productos ya no está disponible. Recarga la página.")
        nombre = v.nombre_completo
        if desde_pedido:
            foto = it.get("opciones_foto") or []
            extra = CERO
        else:
            if v.producto.agotado:
                raise VentaInvalida(f"{v.producto.nombre} está agotado hoy.")
            try:
                foto, extra, _ = resolver_opciones(v.producto, it.get("opciones") or [])
            except OpcionInvalida as e:
                raise VentaInvalida(str(e))
        cantidad = _dec(it.get("cantidad"), f"Cantidad de {nombre}")
        if cantidad <= 0:
            raise VentaInvalida(f"La cantidad de {nombre} debe ser mayor que cero.")
        if not v.producto.fraccionable and cantidad != cantidad.to_integral_value():
            raise VentaInvalida(f"{nombre} se vende por unidades enteras.")
        lista = v.precio_venta + extra
        if desde_pedido and it.get("precio") not in (None, ""):
            lista = dinero(_dec(it["precio"], f"Precio de {nombre}"))  # el precio que tenía al pedirlo
        precio = lista
        if puede_cambiar_precio and it.get("precio") not in (None, ""):
            precio = dinero(_dec(it["precio"], f"Precio de {nombre}"))
        importe = dinero(precio * cantidad)
        cortesia = it.get("cortesia") if desde_pedido else None  # solo llega desde una mesa (ya autorizada)
        if cortesia:
            precio, importe = CERO, CERO
        lineas.append((v, cantidad, precio, lista, importe, foto, cortesia))
        subtotal += importe

    descuento = dinero(_dec(descuento or 0, "Descuento"))
    if descuento and not puede_descontar:
        raise VentaInvalida("No tienes permiso para dar descuentos.")
    descuento_motivo = " ".join(str(descuento_motivo or "").split())[:120]
    if descuento > subtotal:
        raise VentaInvalida("El descuento no puede ser mayor que el total.")
    total = subtotal - descuento
    propina = dinero(_dec(propina or 0, "Propina"))
    if propina:
        from core.models import Ajustes

        if not Ajustes.cargar().propina_activa:
            raise VentaInvalida("La propina no está activada.")
    a_cobrar = total + propina

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
    if pagado < a_cobrar:
        raise VentaInvalida(f"Falta cobrar S/ {a_cobrar - pagado:.2f}.")
    vuelto = pagado - a_cobrar
    efectivo = por_metodo.get(MetodoPago.EFECTIVO, {}).get("monto", CERO)
    if vuelto > efectivo:
        raise VentaInvalida("Con Yape, Plin, tarjeta o transferencia se cobra el monto exacto: el vuelto solo sale del efectivo.")

    from caja.servicios import CajaError, sesion_para_vender
    from clientes.servicios import ClienteError, modulo_activo, resolver_cliente, validar_fiado

    credito = por_metodo.get(MetodoPago.CREDITO, {}).get("monto", CERO)

    try:
        sesion = sesion_para_vender(usuario)
    except CajaError as e:
        raise VentaInvalida(str(e))

    try:
        with transaction.atomic():
            cliente = None
            try:
                if modulo_activo() and (cliente_id or str(cliente_documento or "").strip() or (credito and cliente_nombre)):
                    cliente = resolver_cliente(cliente_id, cliente_nombre, cliente_documento)
                validar_fiado(cliente, credito, puede_fiar, puede_exceder_limite)
            except ClienteError as e:
                raise VentaInvalida(str(e))
            if cliente:
                cliente_nombre, cliente_documento = cliente.nombre, cliente.numero_documento
            venta = Venta.objects.create(
                cliente=cliente,
                numero=Correlativo.siguiente("venta"), usuario=usuario, subtotal=subtotal, descuento=descuento,
                total=total, propina=propina, sesion_caja=sesion, atendio=atendio,
                descuento_motivo=descuento_motivo if descuento else "", descuento_por=(descuento_por or usuario) if descuento else None, recibido=efectivo if efectivo else None, vuelto=vuelto, token=token or None,
                cliente_nombre=" ".join(str(cliente_nombre or "").split())[:150],
                cliente_documento="".join(c for c in str(cliente_documento or "") if c.isalnum())[:11],
                nota=str(nota or "").strip()[:200],
            )
            for v, cantidad, precio, lista, importe, foto, cortesia in lineas:
                VentaItem.objects.create(venta=venta, variante=v, descripcion=descripcion_con_opciones(v.nombre_completo, foto)[:240],
                                         opciones=foto, cantidad=cantidad, cortesia=bool(cortesia),
                                         cortesia_motivo=(cortesia or {}).get("motivo", "")[:120], cortesia_por_id=(cortesia or {}).get("por"),
                                         precio_unitario=precio, precio_lista=lista, costo_unitario=v.costo_efectivo,
                                         subtotal=importe)
                if v.producto.maneja_stock:
                    mover_stock(v, -cantidad, MovimientoStock.Tipo.VENTA, usuario, referencia=f"Venta {venta.numero_str}")
            for metodo, m in por_metodo.items():
                monto = m["monto"] - (vuelto if metodo == MetodoPago.EFECTIVO else CERO)
                if monto > 0:
                    Pago.objects.create(venta=venta, metodo=metodo, monto=monto, referencia=m["referencia"])
            if despues:
                despues(venta)
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
        _devolver_efectivo(v, usuario, motivo)
        from mesas.servicios import reabrir_por_anulacion

        v.cuenta_reabierta = reabrir_por_anulacion(v)
        v.estado = Venta.Estado.ANULADA
        v.anulada_en = timezone.now()
        v.anulada_por = usuario
        v.motivo_anulacion = motivo
        v.save(update_fields=["estado", "anulada_en", "anulada_por", "motivo_anulacion"])
        from .senales import venta_anulada

        venta_anulada.send(sender=Venta, venta=v, usuario=usuario, motivo=motivo)
    return v


def _devolver_efectivo(venta, usuario, motivo):
    """Si la venta era de una caja ya cerrada, el efectivo que se devuelve sale de la caja abierta de quien anula."""
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import movimiento

    if venta.sesion_caja_id is None or venta.sesion_caja.abierta:
        return  # mientras la caja siga abierta, la venta anulada simplemente deja de sumar
    efectivo = sum((p.monto for p in venta.pagos.filter(metodo=MetodoPago.EFECTIVO)), CERO)
    actual = SesionCaja.abierta_de(usuario)
    if efectivo and actual:
        movimiento(actual, MovimientoCaja.Tipo.EGRESO, efectivo, f"Devolución por anular la venta {venta.numero_str}: {motivo}",
                   usuario, MovimientoCaja.Categoria.DEVOLUCION, automatico=True)


def resumen(ventas):
    """Totales de un conjunto de ventas pagadas: total, cantidad, ticket promedio, por método, costo."""
    from django.db.models import Count, Sum

    pagadas = ventas.filter(estado=Venta.Estado.PAGADA)
    t = pagadas.aggregate(total=Sum("total"), n=Count("id"), descuentos=Sum("descuento"), propinas=Sum("propina"))
    total, n = t["total"] or CERO, t["n"] or 0
    metodos = (Pago.objects.filter(venta__in=pagadas).values("metodo").annotate(total=Sum("monto"), n=Count("venta", distinct=True))
               .order_by("-total"))
    nombres = dict(MetodoPago.choices)
    costo = CERO
    for i in VentaItem.objects.filter(venta__in=pagadas, costo_unitario__isnull=False).values("cantidad", "costo_unitario"):
        costo += i["cantidad"] * i["costo_unitario"]
    sin_costo = VentaItem.objects.filter(venta__in=pagadas, costo_unitario__isnull=True).exists()
    total = dinero(Decimal(total))
    return {
        "total": total, "n": n, "promedio": dinero(total / n) if n else CERO, "descuentos": t["descuentos"] or CERO,
        "metodos": [{"metodo": nombres.get(m["metodo"], m["metodo"]), "codigo": m["metodo"], "total": dinero(Decimal(m["total"])), "n": m["n"]} for m in metodos],
        "ganancia": total - dinero(costo), "sin_costo": sin_costo,
        "propinas": dinero(Decimal(t["propinas"] or 0)),
        "anuladas": ventas.filter(estado=Venta.Estado.ANULADA).count(),
    }
