"""Registrar y anular ventas. Aquí se valida todo lo que llega del punto de venta: el navegador no es de fiar."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from productos.models import MovimientoStock, Variante
from productos.servicios import OpcionInvalida, consumo, descripcion_con_opciones, mover_stock, resolver_opciones

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


def falta_operacion(metodo, referencia):
    """Con «pedir el N° de operación» encendido, Yape y Plin no se registran sin él (venta, pago de fiado o de cuotas).
    Devuelve el mensaje de error o "" si está bien."""
    if metodo in (MetodoPago.YAPE, MetodoPago.PLIN) and not str(referencia or "").strip():
        from core.models import Ajustes

        if Ajustes.cargar().exigir_operacion:
            return f"Escribe el N° de operación del {MetodoPago(metodo).label}."
    return ""


def _momento(valor):
    """Cuándo se pidió un plato (para las promociones por horario); None = ahora."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(valor)) if valor else None
    except ValueError:
        return None


def armar_lineas(items, desde_pedido=False, cliente_id=None, puede_cambiar_precio=False):
    """Las líneas de una venta con su precio (listas de precios) y sus promociones, sin guardar nada.
    La usan registrar_venta y la cotización que muestra la pantalla antes de cobrar: así lo que se ve es lo que se cobra."""
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

    # Listas de precios: el precio por cantidad cuenta todo lo que se lleva de ese producto; el del cliente, por su lista
    from productos import precios as reglas

    lista_cliente, filas_precio, por_producto = None, {}, {}
    if not desde_pedido and reglas.activa():
        lista_cliente = reglas.lista_de(cliente_id)
        filas_precio = reglas.especiales({v.producto_id for v in variantes.values()})
        for it, vid in zip(items, ids):
            v = variantes.get(vid)
            try:
                q = Decimal(str(it.get("cantidad")))
            except (InvalidOperation, TypeError):
                continue
            if v is not None and q > 0:
                por_producto[v.producto_id] = por_producto.get(v.producto_id, CERO) + q

    lineas = []
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
        regla = ""
        if filas_precio or lista_cliente:
            base, regla = reglas.precio(v, por_producto.get(v.producto_id, cantidad), lista_cliente, filas_precio.get(v.producto_id, ()))
        else:
            base = v.precio_venta
        lista = base + extra
        if desde_pedido and it.get("precio") not in (None, ""):
            lista = dinero(_dec(it["precio"], f"Precio de {nombre}"))  # el precio que tenía al pedirlo
        precio = lista
        if puede_cambiar_precio and it.get("precio") not in (None, ""):
            precio = dinero(_dec(it["precio"], f"Precio de {nombre}"))
        importe = dinero(precio * cantidad)
        cortesia = it.get("cortesia") if desde_pedido else None  # solo llega desde una mesa (ya autorizada)
        if cortesia:
            precio, importe = CERO, CERO
        lineas.append({"v": v, "cantidad": cantidad, "precio": precio, "lista": lista, "importe": importe, "foto": foto,
                       "normal": (v.precio_venta + extra) if regla else lista,
                       "cortesia": cortesia, "regla": regla, "momento": _momento(it.get("momento")) if desde_pedido else None,
                       "promo": None, "promo_desc": CERO})
    from productos.promociones import aplicar

    aplicar(lineas)  # promociones (2×1, %, precio especial): rebajan el importe de la línea
    subtotal = sum((l["importe"] for l in lineas), CERO)
    return lineas, subtotal


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
    lineas, subtotal = armar_lineas(items, desde_pedido, cliente_id, puede_cambiar_precio)

    from core.models import Ajustes

    ajustes = Ajustes.cargar()
    descuento = dinero(_dec(descuento or 0, "Descuento"))
    if descuento and not ajustes.descuentos_activos:
        raise VentaInvalida("Los descuentos están desactivados en Datos del negocio.")
    if descuento and not puede_descontar:
        raise VentaInvalida("No tienes permiso para dar descuentos.")
    descuento_motivo = " ".join(str(descuento_motivo or "").split())[:120]
    if descuento > subtotal:
        raise VentaInvalida("El descuento no puede ser mayor que el total.")
    total = subtotal - descuento
    propina = dinero(_dec(propina or 0, "Propina"))
    if propina:
        if not ajustes.propina_activa:
            raise VentaInvalida("La propina no está activada.")
    a_cobrar = total + propina

    # Pagos: se juntan por método. El vuelto solo puede salir del efectivo.
    por_metodo = {}
    for p in pagos or []:
        metodo = p.get("metodo")
        if metodo not in MetodoPago.values:
            raise VentaInvalida("Método de pago no válido.")
        monto = dinero(_dec(p.get("monto") or 0, "Monto"))
        if monto > 0 and metodo not in ajustes.metodos_aceptados and metodo != MetodoPago.SALDO:
            raise VentaInvalida(f"El negocio no acepta pagos con {MetodoPago(metodo).label}.")
        if monto > 0:
            m = por_metodo.setdefault(metodo, {"monto": CERO, "referencia": ""})
            m["monto"] += monto
            m["referencia"] = (m["referencia"] or str(p.get("referencia") or "").strip())[:60]
    for metodo, m in por_metodo.items():
        if error := falta_operacion(metodo, m["referencia"]):
            raise VentaInvalida(error)
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
            from caja.servicios import bloquear_abierta

            try:
                bloquear_abierta(sesion)  # antes del correlativo: el mismo orden de bloqueo que el cierre
            except CajaError as e:
                raise VentaInvalida(str(e))
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
            for ln in lineas:
                v, cantidad, foto, cortesia = ln["v"], ln["cantidad"], ln["foto"], ln["cortesia"]
                if not desde_pedido:  # en mesas y delivery se descontaron al pedir
                    from productos.servicios import PorcionesError, tomar_porciones

                    try:
                        tomar_porciones(v.producto_id, cantidad)
                    except PorcionesError as e:
                        raise VentaInvalida(str(e))
                VentaItem.objects.create(venta=venta, variante=v, descripcion=descripcion_con_opciones(v.nombre_completo, foto)[:240],
                                         opciones=foto, cantidad=cantidad, cortesia=bool(cortesia),
                                         cortesia_motivo=(cortesia or {}).get("motivo", "")[:120], cortesia_por_id=(cortesia or {}).get("por"),
                                         precio_unitario=ln["precio"], precio_lista=ln["lista"],
                                         precio_regla=ln["regla"] if ln["precio"] == ln["lista"] else "",
                                         promo=ln["promo"], promo_descuento=ln["promo_desc"],
                                         costo_unitario=v.costo_efectivo, subtotal=ln["importe"])
                for vs, q in consumo(v, cantidad, foto):  # el producto, lo que trae el combo y las opciones que se cuentan
                    mover_stock(vs, -q, MovimientoStock.Tipo.VENTA, usuario, referencia=f"Venta {venta.numero_str}",
                                nota="" if vs.pk == v.pk else f"En {v.nombre_completo}"[:200])
            for metodo, m in por_metodo.items():
                monto = m["monto"] - (vuelto if metodo == MetodoPago.EFECTIVO else CERO)
                if monto > 0:
                    Pago.objects.create(venta=venta, metodo=metodo, monto=monto, referencia=m["referencia"])
            con_saldo = por_metodo.get(MetodoPago.SALDO, {}).get("monto", CERO)
            if con_saldo > 0:
                from clientes.saldo import SaldoError, usar

                if cliente is None:
                    raise VentaInvalida("Para pagar con saldo a favor, elige al cliente.")
                try:
                    usar(cliente, con_saldo, venta, usuario)
                except SaldoError as e:
                    raise VentaInvalida(str(e))
            if cliente:
                from clientes.saldo import ganar_por_venta

                venta.monedero = ganar_por_venta(venta, usuario)  # función Monedero: un % de lo pagado vuelve como saldo
            _anotar_rebajas(venta, lineas, descuento, usuario, descuento_por)
            if despues:
                despues(venta)
    except IntegrityError:
        if token:  # doble clic: la otra petición ya la registró
            previa = Venta.objects.filter(token=token).first()
            if previa:
                return previa
        raise
    return venta


def _anotar_rebajas(venta, lineas, descuento, usuario, descuento_por):
    """Descuentos y precios cambiados al vender quedan en la bitácora (las cortesías de mesa se anotan al darlas)."""
    from core.bitacora import anotar

    if descuento:
        anotar("venta.descuento", f"Descuento de S/ {descuento:.2f} en la venta {venta.numero_str}"
               + (f": {venta.descuento_motivo}" if venta.descuento_motivo else ""), objeto=venta, usuario=usuario,
               despues={"descuento": descuento, "autorizo": str(descuento_por or usuario)})
    cambiados = [(l["v"], l["precio"], l["lista"]) for l in lineas if l["precio"] != l["lista"] and not l["cortesia"]]
    if cambiados:
        anotar("venta.precio", f"Precio cambiado en la venta {venta.numero_str}: " + ", ".join(
            f"{v.nombre_completo} S/ {lista:.2f} → S/ {precio:.2f}" for v, precio, lista in cambiados), objeto=venta, usuario=usuario)


def anular_venta(venta, usuario, motivo):
    """Anula la venta y devuelve al stock lo vendido. Los datos no se borran."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise VentaInvalida("Indica el motivo de la anulación.")
    with transaction.atomic():
        v = Venta.objects.select_for_update().get(pk=venta.pk)
        if v.anulada:
            raise VentaInvalida("Esta venta ya estaba anulada.")
        if v.devoluciones.exists():
            raise VentaInvalida("Esta venta tiene devoluciones: para lo que queda, usa «Devolver productos».")
        for item in v.items.select_related("variante__producto"):
            for vs, q in consumo(item.variante, item.cantidad, item.opciones):
                mover_stock(vs, q, MovimientoStock.Tipo.DEVOLUCION, usuario,
                            nota=f"Anulación: {motivo}", referencia=f"Venta {v.numero_str}")
        _devolver_efectivo(v, usuario, motivo)
        from clientes.saldo import devolver_uso

        devolver_uso(v)  # si se pagó con saldo a favor, el saldo vuelve
        if v.cliente_id:
            from clientes.saldo import ganado_en, quitar

            quitar(v.cliente_id, ganado_en(v), usuario, f"Venta {v.numero_str} anulada", venta=v)  # el monedero que generó
        from mesas.servicios import reabrir_por_anulacion

        v.cuenta_reabierta = reabrir_por_anulacion(v)
        v.estado = Venta.Estado.ANULADA
        v.anulada_en = timezone.now()
        v.anulada_por = usuario
        v.motivo_anulacion = motivo
        v.save(update_fields=["estado", "anulada_en", "anulada_por", "motivo_anulacion"])
        from core.bitacora import anotar

        anotar("venta.anulada", f"Venta {v.numero_str} por S/ {v.total:.2f} anulada: {motivo}", objeto=v, usuario=usuario,
               despues={"total": v.total, "motivo": motivo, "vendio": str(v.usuario)})
        from .senales import venta_anulada

        venta_anulada.send(sender=Venta, venta=v, usuario=usuario, motivo=motivo)
    return v


def _devolver_efectivo(venta, usuario, motivo):
    """Si la venta era de una caja ya cerrada, el efectivo que se devuelve sale de la caja abierta de quien anula."""
    from caja.servicios import CajaError, devolver_efectivo

    efectivo = sum((p.monto for p in venta.pagos.filter(metodo=MetodoPago.EFECTIVO)), CERO)
    try:
        devolver_efectivo(venta.sesion_caja, efectivo, usuario, f"Devolución por anular la venta {venta.numero_str}: {motivo}")
    except CajaError as e:
        raise VentaInvalida(str(e))


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
