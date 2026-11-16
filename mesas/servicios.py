"""Reglas de las mesas: abrir, agregar, enviar a cocina, mover, juntar, quitar, cobrar y anular."""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from productos.models import Variante
from productos.servicios import OpcionInvalida, resolver_opciones

from .models import CERO, Cuenta, ItemCuenta, Mesa


class MesaError(Exception):
    pass


def cuenta_de_mesa(mesa):
    """La cuenta abierta que ocupa la mesa: la suya propia o la de la mesa a la que está pegada."""
    if mesa is None:
        return None
    propia = mesa.cuentas.filter(estado=Cuenta.Estado.ABIERTA).first()
    return propia or Cuenta.objects.filter(mesas_unidas=mesa, estado=Cuenta.Estado.ABIERTA).first()


def abrir_cuenta(mozo, mesa=None, personas=1, nombre=""):
    if mesa is not None and not mesa.activa:
        raise MesaError("Esa mesa está desactivada.")
    pegada = Cuenta.objects.filter(mesas_unidas=mesa, estado=Cuenta.Estado.ABIERTA).first() if mesa is not None else None
    if pegada:
        raise MesaError(f"La mesa {mesa.nombre} está junto con {pegada.titulo}.")
    try:
        with transaction.atomic():
            return Cuenta.objects.create(mesa=mesa, mozo=mozo, personas=max(0, min(int(personas or 0), 99)), nombre=" ".join(str(nombre or "").split())[:60],
                                         tipo=Cuenta.Tipo.MESA if mesa else Cuenta.Tipo.LLEVAR)
    except IntegrityError:
        raise MesaError(f"La mesa {mesa.nombre} ya está ocupada.")


# --- Delivery ------------------------------------------------------------------------

def _limpio(texto, largo):
    return " ".join(str(texto or "").split())[:largo]


def _monto(texto):
    try:
        m = Decimal(str(texto or "0").replace(",", ".").strip() or "0")
    except ArithmeticError:
        raise MesaError("El costo de envío no es un número.")
    if not m.is_finite() or m < 0 or m > 999:
        raise MesaError("El costo de envío no es válido.")
    return m.quantize(Decimal("0.01"))


def datos_delivery(cuenta, nombre="", telefono="", direccion="", referencia="", paga_con=""):
    """Guarda los datos del pedido y los recuerda en el cliente (con el módulo Clientes activo)."""
    cuenta.nombre = _limpio(nombre, 60)
    cuenta.telefono = "".join(c for c in str(telefono or "") if c.isdigit() or c == "+")[:20]
    cuenta.direccion = _limpio(direccion, 200)
    cuenta.referencia = _limpio(referencia, 200)
    cuenta.paga_con = _limpio(paga_con, 40)
    if not cuenta.direccion:
        raise MesaError("Escribe la dirección de entrega.")
    from core.permisos import modulos_activos

    if cuenta.telefono and "clientes" in modulos_activos():
        from clientes.models import Cliente

        cli = cuenta.cliente or Cliente.objects.filter(telefono=cuenta.telefono, activo=True).first()
        if cli is None and cuenta.nombre:
            cli = Cliente.objects.create(tipo_documento=Cliente.TipoDocumento.SIN, nombre=cuenta.nombre, telefono=cuenta.telefono,
                                         direccion=cuenta.direccion, nota="Cliente de delivery")
        elif cli is not None and (cli.direccion != cuenta.direccion or not cli.telefono):
            cli.direccion, cli.telefono = cuenta.direccion, cli.telefono or cuenta.telefono  # la última dirección queda para la próxima
            cli.save(update_fields=["direccion", "telefono"])
        cuenta.cliente = cli
    cuenta.save()
    return cuenta


def abrir_delivery(mozo, nombre="", telefono="", direccion="", referencia="", paga_con="", costo_envio=None):
    from core.models import Ajustes

    c = Cuenta(mozo=mozo, tipo=Cuenta.Tipo.DELIVERY, estado_envio=Cuenta.Envio.PREPARANDO)
    with transaction.atomic():
        datos_delivery(c, nombre, telefono, direccion, referencia, paga_con)
        poner_envio(c, Ajustes.cargar().delivery_costo if costo_envio in (None, "") else costo_envio, mozo)
    return c


def _producto_envio():
    """Producto interno para cobrar el envío (no sale en el catálogo)."""
    from productos.models import Categoria, Producto

    p = Producto.objects.filter(nombre="Costo de envío (delivery)", tipo="S").first()
    if p is None:
        p = Producto.objects.create(nombre="Costo de envío (delivery)", tipo="S", unidad="SRV", precio=Decimal("0"), maneja_stock=False,
                                    activo=False, descripcion="Lo usa el delivery para cobrar el envío. No borrar.")
    from productos.servicios import asegurar_variante_unica

    return asegurar_variante_unica(p)


def poner_envio(cuenta, monto, usuario):
    """Pone (o cambia) la línea del costo de envío. Ya cobrada, no se toca."""
    _abierta(cuenta)
    monto = _monto(monto)
    with transaction.atomic():
        actual = cuenta.items.filter(es_envio=True, anulado=False).first()
        if actual and actual.venta_id:
            if actual.precio != monto:
                raise MesaError("El envío ya se cobró: no se puede cambiar.")
            return actual
        if actual:
            actual.delete()
        cuenta.costo_envio = monto
        cuenta.save(update_fields=["costo_envio"])
        if not monto:
            return None
        ahora = timezone.now()
        return ItemCuenta.objects.create(cuenta=cuenta, variante=_producto_envio(), descripcion="Costo de envío", cantidad=1, precio=monto,
                                         agregado_por=usuario, es_envio=True, enviado_en=ahora, listo_en=ahora, servido_en=ahora)


def salio_delivery(cuenta, repartidor=""):
    _abierta(cuenta)
    cuenta.estado_envio, cuenta.repartidor, cuenta.salio_en = Cuenta.Envio.EN_CAMINO, _limpio(repartidor, 60), timezone.now()
    cuenta.save(update_fields=["estado_envio", "repartidor", "salio_en"])


def entregar_delivery(cuenta):
    """Marca entregado. Si ya está todo cobrado, el pedido se cierra."""
    _abierta(cuenta)
    ahora = timezone.now()
    cuenta.estado_envio, cuenta.entregado_en = Cuenta.Envio.ENTREGADO, ahora
    campos = ["estado_envio", "entregado_en"]
    if cuenta.pagada():
        cuenta.estado, cuenta.cerrada_en = Cuenta.Estado.COBRADA, ahora
        campos += ["estado", "cerrada_en"]
    cuenta.save(update_fields=campos)


def _abierta(cuenta):
    if not cuenta.abierta:
        raise MesaError("Esta cuenta ya no está abierta.")


def agregar(cuenta, items, usuario):
    """items: [{"variante": id, "cantidad": "2", "nota": "sin cebolla"}]. El precio es el del catálogo en este momento."""
    _abierta(cuenta)
    if not items:
        raise MesaError("No hay nada que agregar.")
    try:
        ids = [int(i["variante"]) for i in items]
    except (KeyError, TypeError, ValueError):
        raise MesaError("Producto no válido.")
    variantes = Variante.objects.select_related("producto__categoria").in_bulk(ids)
    creados = []
    with transaction.atomic():
        for it, vid in zip(items, ids):
            v = variantes.get(vid)
            if v is None or not v.activa or not v.producto.activo:
                raise MesaError("Uno de los productos ya no está disponible. Recarga la página.")
            try:
                cantidad = Decimal(str(it.get("cantidad") or "1"))
            except InvalidOperation:
                raise MesaError("Cantidad no válida.")
            if not cantidad.is_finite() or cantidad <= 0 or cantidad > 999:
                raise MesaError("Cantidad no válida.")
            if not v.producto.fraccionable and cantidad != cantidad.to_integral_value():
                raise MesaError(f"{v.nombre_completo} se pide por unidades enteras.")
            nota = " ".join(str(it.get("nota") or "").split())[:120]
            if v.producto.agotado:
                raise MesaError(f"{v.producto.nombre} está agotado hoy.")
            try:
                foto, extra, _ = resolver_opciones(v.producto, it.get("opciones") or [])
            except OpcionInvalida as e:
                raise MesaError(str(e))
            previo = next((p for p in cuenta.items.filter(variante=v, nota=nota, enviado_en__isnull=True, anulado=False, venta__isnull=True, cortesia=False)
                           if [o["id"] for o in p.opciones or []] == [o["id"] for o in foto]), None)
            if previo:  # mismo plato, misma nota, aún no enviado: se suma
                previo.cantidad += cantidad
                previo.save(update_fields=["cantidad"])
                creados.append(previo)
            else:
                creados.append(ItemCuenta.objects.create(cuenta=cuenta, variante=v, descripcion=v.nombre_completo[:240], opciones=foto, area=v.producto.area_efectiva,
                                                         cantidad=cantidad, precio=v.precio_venta + extra, nota=nota, agregado_por=usuario))
    return creados


def enviar_cocina(cuenta):
    """Marca lo pendiente como enviado. Devuelve la hora del envío (para la comanda) o None si no había nada."""
    _abierta(cuenta)
    ahora = timezone.now()
    n = cuenta.items.filter(anulado=False, enviado_en__isnull=True).update(enviado_en=ahora)
    # Lo que saca el mozo (gaseosas, agua) no espera a nadie: queda listo para llevar a la mesa
    cuenta.items.filter(enviado_en=ahora, area="MOZ", es_envio=False).update(listo_en=ahora)
    return ahora if n else None


def marcar_listo(items, listo=True):
    """Cocina: marca (o desmarca) platos como listos para servir."""
    ahora = timezone.now() if listo else None
    return ItemCuenta.objects.filter(pk__in=[i.pk for i in items], anulado=False, enviado_en__isnull=False).update(listo_en=ahora)


def marcar_servido(cuenta):
    """Mozo: ya llevó a la mesa todo lo que la cocina marcó como listo."""
    return cuenta.items.filter(listo_en__isnull=False, servido_en__isnull=True).update(servido_en=timezone.now())


def cambiar_cantidad(item, delta):
    """+1 / −1 a algo que todavía no se envió a cocina. Si llega a 0, se quita."""
    _abierta(item.cuenta)
    if item.enviado or item.venta_id or item.anulado:
        raise MesaError("Eso ya se envió a cocina: para cambiarlo, quítalo con un motivo.")
    nueva = item.cantidad + Decimal(delta)
    if nueva <= 0:
        item.delete()
    else:
        item.cantidad = nueva
        item.save(update_fields=["cantidad"])


def quitar(item, usuario, motivo="", puede_anular=False):
    _abierta(item.cuenta)
    if item.venta_id:
        raise MesaError("Eso ya se cobró: anula la venta si hace falta.")
    if not item.enviado:
        item.delete()
        return
    if not puede_anular:
        raise MesaError("Ya se envió a cocina: solo alguien con permiso puede quitarlo.")
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise MesaError("Indica por qué se quita (ej.: el cliente cambió de pedido).")
    item.anulado, item.motivo_anulacion, item.anulado_por = True, motivo, usuario
    item.save(update_fields=["anulado", "motivo_anulacion", "anulado_por"])


def cortesia(item, autoriza, motivo, cantidad=None, quitar=False):
    """Marca un plato (o parte de sus unidades) como cortesía: se prepara y se sirve, pero no se cobra."""
    _abierta(item.cuenta)
    if item.venta_id or item.anulado:
        raise MesaError("Ese plato ya se cobró o se quitó.")
    if quitar:
        item.cortesia, item.cortesia_motivo, item.cortesia_por = False, "", None
        item.save(update_fields=["cortesia", "cortesia_motivo", "cortesia_por"])
        return item
    motivo = " ".join(str(motivo or "").split())[:120]
    if not motivo:
        raise MesaError("Indica el motivo de la cortesía.")
    if item.cortesia:
        raise MesaError("Ya es cortesía.")
    try:
        cantidad = Decimal(str(cantidad)) if cantidad not in (None, "") else item.cantidad
    except ArithmeticError:
        raise MesaError("Cantidad no válida.")
    if not cantidad.is_finite() or cantidad <= 0 or cantidad > item.cantidad:
        raise MesaError("Cantidad no válida.")
    with transaction.atomic():
        if cantidad < item.cantidad:  # solo algunas unidades: se separan en otra línea
            item.cantidad -= cantidad
            item.save(update_fields=["cantidad"])
            item.pk = None
            item.cantidad = cantidad
        item.cortesia, item.cortesia_motivo, item.cortesia_por = True, motivo, autoriza
        item.save()
    return item


def _libre(mesa, cuenta=None):
    otra = cuenta_de_mesa(mesa)
    if otra and (cuenta is None or otra.pk != cuenta.pk):
        raise MesaError(f"La mesa {mesa.nombre} está ocupada ({otra.titulo}).")
    if not mesa.activa:
        raise MesaError(f"La mesa {mesa.nombre} está desactivada.")


def cambiar_personas(cuenta, personas):
    """Corrige cuántas personas hay. Sirve para los cubiertos, el reparto en partes iguales y los reportes."""
    _abierta(cuenta)
    try:
        n = int(personas)
    except (TypeError, ValueError):
        raise MesaError("Número de personas no válido.")
    if not 1 <= n <= 99:
        raise MesaError("Número de personas no válido.")
    cuenta.personas = n
    cuenta.save(update_fields=["personas"])


def mover(cuenta, mesa):
    """El grupo se muda a otra mesa libre (las mesas que tenía pegadas se liberan)."""
    _abierta(cuenta)
    _libre(mesa, cuenta)
    try:
        with transaction.atomic():
            Mesa.objects.filter(unida_a=cuenta).update(unida_a=None)
            cuenta.mesa = mesa
            cuenta.save(update_fields=["mesa"])
    except IntegrityError:
        raise MesaError(f"La mesa {mesa.nombre} se acaba de ocupar.")


def unir_mesas(cuenta, mesas):
    """Pega mesas libres a la cuenta (una familia que junta 3 mesas). Devuelve cuántas se unieron."""
    _abierta(cuenta)
    if not cuenta.mesa_id:
        raise MesaError("Solo se pueden juntar mesas a una cuenta de mesa.")
    mesas = [m for m in mesas if m.pk != cuenta.mesa_id]
    if not mesas:
        raise MesaError("Elige al menos una mesa libre.")
    with transaction.atomic():
        for m in Mesa.objects.select_for_update().filter(pk__in=[m.pk for m in mesas]):
            _libre(m, cuenta)
            m.unida_a = cuenta
            m.save(update_fields=["unida_a"])
    return len(mesas)


def separar_mesa(cuenta, mesa):
    _abierta(cuenta)
    mesa.refresh_from_db(fields=["unida_a"])
    if mesa.unida_a_id != cuenta.pk or mesa.pk == cuenta.mesa_id:
        raise MesaError(f"La mesa {mesa.nombre} no está junto con esta cuenta.")
    mesa.unida_a = None
    mesa.save(update_fields=["unida_a"])


def juntar(origen, destino):
    """Une dos cuentas abiertas (dos grupos que se juntan): todo pasa a `destino` y la mesa de origen queda pegada a ella."""
    _abierta(origen)
    _abierta(destino)
    if origen.pk == destino.pk:
        raise MesaError("Elige otra mesa.")
    with transaction.atomic():
        origen.items.update(cuenta=destino)
        destino.personas += origen.personas
        destino.pidio_cuenta = destino.pidio_cuenta or origen.pidio_cuenta
        destino.save(update_fields=["personas", "pidio_cuenta"])
        titulo = destino.titulo
        origen.estado = Cuenta.Estado.ANULADA
        origen.cerrada_en = timezone.now()
        origen.motivo_anulacion = f"Se juntó con {titulo}"
        origen.save(update_fields=["estado", "cerrada_en", "motivo_anulacion"])
        pegar = [m for m in Mesa.objects.filter(unida_a=origen)] + ([origen.mesa] if origen.mesa_id else [])
        for m in pegar:
            if m.pk != destino.mesa_id:
                m.unida_a = destino
                m.save(update_fields=["unida_a"])


def anular_cuenta(cuenta, usuario, motivo="", puede_anular=False):
    _abierta(cuenta)
    if cuenta.items.filter(venta__isnull=False).exists():
        raise MesaError("Parte de la cuenta ya se cobró. Cobra el resto o quita los productos.")
    if cuenta.items.filter(anulado=False, enviado_en__isnull=False).exists():
        if not puede_anular:
            raise MesaError("Ya se enviaron productos a cocina: solo alguien con permiso puede anular la cuenta.")
        if not str(motivo or "").strip():
            raise MesaError("Indica el motivo.")
    cuenta.estado = Cuenta.Estado.ANULADA
    cuenta.cerrada_en = timezone.now()
    cuenta.motivo_anulacion = str(motivo or "Mesa liberada sin consumo").strip()[:200]
    cuenta.save(update_fields=["estado", "cerrada_en", "motivo_anulacion"])


def reabrir_por_anulacion(venta):
    """Si se anula la venta con que se cobró una mesa, esos platos vuelven a quedar por cobrar
    (por ejemplo, se cobró con el método equivocado). Devuelve la cuenta reabierta o None."""
    items = list(ItemCuenta.objects.filter(venta=venta).select_related("cuenta__mesa"))
    if not items:
        return None
    cuenta = items[0].cuenta
    ItemCuenta.objects.filter(venta=venta).update(venta=None)
    if cuenta.estado != Cuenta.Estado.ABIERTA:
        ocupada = cuenta.mesa_id and Cuenta.objects.filter(mesa_id=cuenta.mesa_id, estado=Cuenta.Estado.ABIERTA).exists()
        if ocupada:  # la mesa ya tiene otros clientes: queda como cuenta aparte
            cuenta.nombre = f"Mesa {cuenta.mesa.nombre} (cobro anulado)"[:60]
            cuenta.mesa = None
        cuenta.estado = Cuenta.Estado.ABIERTA
        cuenta.cerrada_en = None
        cuenta.save(update_fields=["estado", "cerrada_en", "mesa", "nombre"])
    return cuenta


def cobrar(cuenta, cajero, pagos, item_ids=None, propina=0, cliente_nombre="", cliente_documento="", nota="", token=None,
           cliente_id=None, puede_fiar=False, puede_exceder_limite=False, descuento=0, descuento_motivo="", descuento_por=None,
           liberar=True):
    """Cobra todo lo pendiente (o solo los ítems elegidos, para dividir la cuenta) creando una venta normal.

    - Lo cobrado que aún no se había enviado a cocina se envía en ese momento (nunca se cobra algo que cocina no sabe).
      La hora de ese envío queda en `venta.enviado_cocina` (para la comanda), o None.
    - Si ya no queda nada por cobrar y `liberar`, la cuenta se cierra y la mesa queda libre. Si no, la mesa queda
      "pagada": los clientes siguen ahí (o esperan su comida) y se libera después con `liberar_mesa`."""
    from ventas.servicios import VentaInvalida, registrar_venta

    _abierta(cuenta)
    pendientes = list(cuenta.por_cobrar())
    if item_ids:
        elegidos = {int(i) for i in item_ids}
        pendientes = [i for i in pendientes if i.pk in elegidos]
    if not pendientes:
        raise MesaError("No hay nada por cobrar.")
    ids = [i.pk for i in pendientes]
    enviado = {}

    def marcar(venta):
        n = ItemCuenta.objects.select_for_update().filter(pk__in=ids, venta__isnull=True, anulado=False).update(venta=venta)
        if n != len(ids):
            raise VentaInvalida("Alguien cambió esta cuenta mientras cobrabas. Revísala y vuelve a intentar.")
        ahora = timezone.now()
        if ItemCuenta.objects.filter(pk__in=ids, enviado_en__isnull=True).update(enviado_en=ahora):
            enviado["en"] = ahora
        if liberar and not ItemCuenta.objects.filter(cuenta=cuenta, anulado=False, venta__isnull=True).exists():
            Cuenta.objects.filter(pk=cuenta.pk).update(estado=Cuenta.Estado.COBRADA, cerrada_en=ahora)

    try:
        venta = registrar_venta(
            cajero, [{"variante": i.variante_id, "cantidad": str(i.cantidad), "precio": str(i.precio), "opciones_foto": i.opciones,
                      "cortesia": {"motivo": i.cortesia_motivo, "por": i.cortesia_por_id} if i.cortesia else None}
                     for i in pendientes],
            pagos, cliente_nombre=cliente_nombre, cliente_documento=cliente_documento, nota=(nota or cuenta.titulo)[:200],
            token=token, puede_cambiar_precio=True, puede_descontar=descuento_por is not None, propina=propina, atendio=cuenta.mozo,
            despues=marcar, descuento=descuento, descuento_motivo=descuento_motivo, descuento_por=descuento_por,
            desde_pedido=True, cliente_id=cliente_id, puede_fiar=puede_fiar, puede_exceder_limite=puede_exceder_limite)
    except VentaInvalida as e:
        raise MesaError(str(e))
    venta.enviado_cocina = enviado.get("en")
    return venta


def falta_de_cocina(items):
    """¿Algo de estos platos todavía no sale de cocina? (sin enviar, o enviado y no marcado listo con pantalla de cocina)"""
    from core.models import Ajustes

    con_pantalla = Ajustes.cargar().cocina_pantalla
    return any(not i.anulado and (not i.enviado_en or (con_pantalla and not i.listo_en)) for i in items)


def liberar_mesa(cuenta):
    """Cierra una cuenta ya pagada: los clientes se fueron y la mesa queda libre."""
    _abierta(cuenta)
    if cuenta.por_cobrar().exists():
        raise MesaError("Todavía hay productos por cobrar. Cóbralos o quítalos antes de liberar la mesa.")
    if not cuenta.items.filter(anulado=False, venta__isnull=False).exists():
        raise MesaError("Esta cuenta no tiene nada cobrado.")
    cuenta.estado = Cuenta.Estado.COBRADA
    cuenta.cerrada_en = timezone.now()
    cuenta.save(update_fields=["estado", "cerrada_en"])
