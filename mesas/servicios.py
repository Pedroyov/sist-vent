"""Reglas de las mesas: abrir, agregar, enviar a cocina, mover, juntar, quitar, cobrar y anular."""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from productos.models import Variante
from productos.servicios import OpcionInvalida, resolver_opciones

from .models import CERO, Cuenta, ItemCuenta, Mesa


class MesaError(Exception):
    pass


def abrir_cuenta(mozo, mesa=None, personas=1, nombre=""):
    if mesa is not None and not mesa.activa:
        raise MesaError("Esa mesa está desactivada.")
    try:
        with transaction.atomic():
            return Cuenta.objects.create(mesa=mesa, mozo=mozo, personas=max(1, min(int(personas or 1), 99)), nombre=nombre[:60])
    except IntegrityError:
        raise MesaError(f"La mesa {mesa.nombre} ya está ocupada.")


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
    variantes = Variante.objects.select_related("producto").in_bulk(ids)
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
                creados.append(ItemCuenta.objects.create(cuenta=cuenta, variante=v, descripcion=v.nombre_completo[:240], opciones=foto,
                                                         cantidad=cantidad, precio=v.precio_venta + extra, nota=nota, agregado_por=usuario))
    return creados


def enviar_cocina(cuenta):
    """Marca lo pendiente como enviado. Devuelve la hora del envío (para la comanda) o None si no había nada."""
    _abierta(cuenta)
    ahora = timezone.now()
    n = cuenta.items.filter(anulado=False, enviado_en__isnull=True).update(enviado_en=ahora)
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


def mover(cuenta, mesa):
    _abierta(cuenta)
    if mesa.cuentas.filter(estado=Cuenta.Estado.ABIERTA).exists():
        raise MesaError(f"La mesa {mesa.nombre} está ocupada. Usa «Juntar» si quieres unir las cuentas.")
    cuenta.mesa = mesa
    try:
        with transaction.atomic():
            cuenta.save(update_fields=["mesa"])
    except IntegrityError:
        raise MesaError(f"La mesa {mesa.nombre} se acaba de ocupar.")


def juntar(origen, destino):
    """Pasa todo lo de una cuenta a otra (mesas juntadas). La de origen queda libre."""
    _abierta(origen)
    _abierta(destino)
    if origen.pk == destino.pk:
        raise MesaError("Elige otra mesa.")
    with transaction.atomic():
        origen.items.update(cuenta=destino)
        destino.personas += origen.personas
        destino.save(update_fields=["personas"])
        origen.estado = Cuenta.Estado.ANULADA
        origen.cerrada_en = timezone.now()
        origen.motivo_anulacion = f"Se juntó con {destino.titulo}"
        origen.save(update_fields=["estado", "cerrada_en", "motivo_anulacion"])


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
           cliente_id=None, puede_fiar=False, puede_exceder_limite=False, descuento=0, descuento_motivo="", descuento_por=None):
    """Cobra todo lo pendiente (o solo los ítems elegidos, para dividir la cuenta) creando una venta normal.
    Si ya no queda nada por cobrar, la cuenta se cierra y la mesa queda libre."""
    from ventas.servicios import VentaInvalida, registrar_venta

    _abierta(cuenta)
    pendientes = list(cuenta.por_cobrar())
    if item_ids:
        elegidos = {int(i) for i in item_ids}
        pendientes = [i for i in pendientes if i.pk in elegidos]
    if not pendientes:
        raise MesaError("No hay nada por cobrar.")
    ids = [i.pk for i in pendientes]

    def marcar(venta):
        n = ItemCuenta.objects.select_for_update().filter(pk__in=ids, venta__isnull=True, anulado=False).update(venta=venta)
        if n != len(ids):
            raise VentaInvalida("Alguien cambió esta cuenta mientras cobrabas. Revísala y vuelve a intentar.")
        if not ItemCuenta.objects.filter(cuenta=cuenta, anulado=False, venta__isnull=True).exists():
            Cuenta.objects.filter(pk=cuenta.pk).update(estado=Cuenta.Estado.COBRADA, cerrada_en=timezone.now())

    try:
        return registrar_venta(
            cajero, [{"variante": i.variante_id, "cantidad": str(i.cantidad), "precio": str(i.precio), "opciones_foto": i.opciones,
                      "cortesia": {"motivo": i.cortesia_motivo, "por": i.cortesia_por_id} if i.cortesia else None}
                     for i in pendientes],
            pagos, cliente_nombre=cliente_nombre, cliente_documento=cliente_documento, nota=(nota or cuenta.titulo)[:200],
            token=token, puede_cambiar_precio=True, puede_descontar=descuento_por is not None, propina=propina, atendio=cuenta.mozo,
            despues=marcar, descuento=descuento, descuento_motivo=descuento_motivo, descuento_por=descuento_por,
            desde_pedido=True, cliente_id=cliente_id, puede_fiar=puede_fiar, puede_exceder_limite=puede_exceder_limite)
    except VentaInvalida as e:
        raise MesaError(str(e))
