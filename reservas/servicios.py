"""Lógica de reservas: crear y editar (con aviso de choques), estados, llegada a la mesa y mensajes de WhatsApp."""
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from .models import Config, Reserva

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ReservaError(Exception):
    pass


def _limpio(texto, largo):
    return " ".join(str(texto or "").split())[:largo]


def _telefono(texto):
    return "".join(c for c in str(texto or "") if c.isdigit() or c == "+")[:20]


def hora_texto(h):
    """20:30 → «8:30 pm» (para los mensajes al cliente)."""
    return f"{h.hour % 12 or 12}:{h.minute:02d} {'am' if h.hour < 12 else 'pm'}"


def dia_texto(d, hoy=None):
    hoy = hoy or timezone.localdate()
    if d == hoy:
        return "hoy"
    if d == hoy + timedelta(days=1):
        return "mañana"
    return f"el {DIAS[d.weekday()]} {d:%d/%m}"


def _mesa_activa():
    from core.permisos import modulos_activos

    return "mesas" in modulos_activos()


def choques(fecha, hora, mesa, excluir=None, cfg=None):
    """Otras reservas activas de la misma mesa que se cruzan con esta (según la duración de una reserva)."""
    if mesa is None:
        return []
    cfg = cfg or Config.cargar()
    inicio = datetime.combine(fecha, hora)
    dur = timedelta(minutes=cfg.duracion)
    qs = Reserva.objects.filter(fecha=fecha, mesa=mesa, estado__in=Reserva.ACTIVAS)
    if excluir is not None and excluir.pk:
        qs = qs.exclude(pk=excluir.pk)
    return [r for r in qs if abs(datetime.combine(r.fecha, r.hora) - inicio) < dur]


def _recordar_cliente(r):
    """Con el módulo Clientes, la reserva queda en la ficha del cliente (y se crea si es nuevo)."""
    from core.permisos import modulos_activos

    if not r.telefono or "clientes" not in modulos_activos():
        return
    from clientes.models import Cliente

    cli = r.cliente if r.cliente_id and r.cliente.telefono == r.telefono else None
    cli = cli or Cliente.objects.filter(telefono=r.telefono, activo=True).first()
    if cli is None and len(r.telefono) >= 6:
        cli = Cliente.objects.create(tipo_documento=Cliente.TipoDocumento.SIN, nombre=r.nombre, telefono=r.telefono, nota="Cliente de reservas")
    r.cliente = cli


def guardar(usuario, reserva=None, *, fecha, hora, personas, nombre, telefono="", mesa=None, nota="", permitir_choque=False):
    """Crea o edita una reserva. Devuelve (reserva, avisos). Si la mesa ya está reservada a esa hora, pide confirmar."""
    nombre = _limpio(nombre, 60)
    if not nombre:
        raise ReservaError("Escribe el nombre de quien reserva.")
    if not isinstance(fecha, date) or not isinstance(hora, time):
        raise ReservaError("Indica el día y la hora.")
    try:
        personas = int(personas)
    except (TypeError, ValueError):
        raise ReservaError("Indica cuántas personas.")
    if not 1 <= personas <= 200:
        raise ReservaError("El número de personas no es válido.")
    nueva = reserva is None
    if nueva and timezone.make_aware(datetime.combine(fecha, hora)) < timezone.now() - timedelta(hours=1):
        raise ReservaError("Esa fecha y hora ya pasaron.")
    if mesa is not None and not mesa.activa:
        raise ReservaError(f"La mesa {mesa.nombre} está desactivada.")
    cfg = Config.cargar()
    cruce = choques(fecha, hora, mesa, excluir=reserva, cfg=cfg)
    if cruce and not permitir_choque:
        otra = cruce[0]
        raise ReservaError(f"La mesa {mesa.nombre} ya está reservada a las {otra.hora:%H:%M} ({otra.nombre}, {otra.personas} pers.). "
                           "Elige otra mesa, o confirma si igual quieres reservarla.")
    avisos = []
    if mesa is not None and personas > mesa.capacidad:
        avisos.append(f"La mesa {mesa.nombre} es para {mesa.capacidad}: quizá haya que juntar otra.")
    r = reserva or Reserva(creada_por=usuario)
    if not nueva:
        if not r.activa:
            raise ReservaError("Esta reserva ya se cerró: no se puede cambiar.")
        r.cambiada_por, r.cambiada_en = usuario, timezone.now()
    r.fecha, r.hora, r.personas, r.nombre = fecha, hora.replace(second=0, microsecond=0), personas, nombre
    r.telefono, r.mesa, r.nota = _telefono(telefono), mesa, _limpio(nota, 200)
    with transaction.atomic():
        _recordar_cliente(r)
        r.save()
    return r, avisos


def _estado(r, usuario, estado, desde=Reserva.ACTIVAS):
    if r.estado not in desde:
        raise ReservaError(f"La reserva ya está como «{r.get_estado_display()}».")
    r.estado, r.cambiada_por, r.cambiada_en = estado, usuario, timezone.now()
    r.save(update_fields=["estado", "cambiada_por", "cambiada_en"])
    return r


def confirmar(r, usuario):
    return _estado(r, usuario, Reserva.Estado.CONFIRMADA, desde=(Reserva.Estado.PENDIENTE,))


def cancelar(r, usuario):
    return _estado(r, usuario, Reserva.Estado.CANCELADA)


def no_vino(r, usuario):
    return _estado(r, usuario, Reserva.Estado.NO_VINO)


def reabrir(r, usuario):
    """Deshacer «No vino» o «Cancelada» (por ejemplo, llegaron tarde o se marcó por error)."""
    return _estado(r, usuario, Reserva.Estado.CONFIRMADA, desde=(Reserva.Estado.NO_VINO, Reserva.Estado.CANCELADA))


def llego(r, usuario, mesa=None):
    """Llegaron: abre la cuenta de la mesa (la de la reserva o la que se elija) con sus personas.
    Sin el módulo Mesas, solo marca la reserva como «Llegó». Devuelve la cuenta abierta (o None)."""
    if not r.activa:
        raise ReservaError(f"La reserva ya está como «{r.get_estado_display()}».")
    mesa = mesa or r.mesa
    cuenta = None
    with transaction.atomic():
        if _mesa_activa():
            if mesa is None:
                raise ReservaError("Elige la mesa donde se sientan.")
            from mesas.servicios import MesaError, abrir_cuenta

            try:
                cuenta = abrir_cuenta(usuario, mesa, r.personas)
            except MesaError as e:
                raise ReservaError(f"{e} Elige otra mesa.")
            cuenta.nombre = r.nombre[:60]
            campos = ["nombre"]
            if r.cliente_id:
                cuenta.cliente_id = r.cliente_id
                campos.append("cliente")
            cuenta.save(update_fields=campos)
        r.mesa = mesa or r.mesa
        r.cuenta = cuenta
        r.estado, r.cambiada_por, r.cambiada_en = Reserva.Estado.LLEGO, usuario, timezone.now()
        r.save(update_fields=["mesa", "cuenta", "estado", "cambiada_por", "cambiada_en"])
    return cuenta


def cerrar_pasadas(hoy=None):
    """Las reservas de días anteriores que siguen activas quedan como «No vino» (nadie las marcó)."""
    hoy = hoy or timezone.localdate()
    return Reserva.objects.filter(fecha__lt=hoy, estado__in=Reserva.ACTIVAS).update(estado=Reserva.Estado.NO_VINO, cambiada_en=timezone.now())


def del_dia(fecha):
    return Reserva.objects.filter(fecha=fecha).select_related("mesa", "creada_por", "cuenta")


def para_mapa(ahora=None, cfg=None):
    """{mesa_id: reserva} de las mesas que deben verse como reservadas ahora (desde `antes` hasta la tolerancia)."""
    ahora = ahora or timezone.now()
    cfg = cfg or Config.cargar()
    local = timezone.localtime(ahora)
    resultado = {}
    for r in Reserva.objects.filter(fecha=local.date(), estado__in=Reserva.ACTIVAS, mesa__isnull=False).order_by("hora"):
        m = r.momento
        if m - timedelta(minutes=cfg.antes) <= ahora <= m + timedelta(minutes=cfg.tolerancia):
            resultado.setdefault(r.mesa_id, r)
    return resultado


def proximas_hoy(ahora=None, cfg=None):
    """Reservas de hoy que aún se esperan (activas y dentro de la tolerancia), en orden de hora."""
    ahora = ahora or timezone.now()
    cfg = cfg or Config.cargar()
    hoy = timezone.localtime(ahora).date()
    return [r for r in del_dia(hoy).filter(estado__in=Reserva.ACTIVAS) if not r.atrasada(ahora, cfg)]


def atrasadas(ahora=None, cfg=None):
    ahora = ahora or timezone.now()
    cfg = cfg or Config.cargar()
    hoy = timezone.localtime(ahora).date()
    return [r for r in del_dia(hoy).filter(estado__in=Reserva.ACTIVAS) if r.atrasada(ahora, cfg)]


def historial(telefono):
    """Cuántas veces reservó este celular y cuántas no vino (para avisar al tomar la reserva)."""
    tel = "".join(c for c in telefono or "" if c.isdigit())
    if len(tel) < 6:
        return {}
    qs = Reserva.objects.filter(telefono__endswith=tel[-9:])
    ultima = qs.order_by("-fecha", "-hora").first()
    if ultima is None:
        return {}
    return {"nombre": ultima.nombre, "reservas": qs.count(), "no_vino": qs.filter(estado=Reserva.Estado.NO_VINO).count(),
            "llego": qs.filter(estado=Reserva.Estado.LLEGO).count()}


def mensaje(r, hoy=None):
    """Texto para WhatsApp: confirmación (si es otro día) o recordatorio (si es hoy)."""
    from core.models import Ajustes

    negocio = Ajustes.cargar().nombre_mostrar
    hoy = hoy or timezone.localdate()
    pers = f"{r.personas} persona{'s' if r.personas != 1 else ''}"
    if r.fecha == hoy:
        texto = (f"Hola {r.nombre}, le recordamos su reserva de hoy a las {hora_texto(r.hora)} para {pers} en {negocio}. "
                 "Si hay algún cambio, por favor avísenos. ¡Lo esperamos!")
    else:
        texto = (f"Hola {r.nombre}, le confirmamos su reserva en {negocio} para {dia_texto(r.fecha, hoy)} a las {hora_texto(r.hora)}, "
                 f"{pers}. Si no puede venir, por favor avísenos. ¡Lo esperamos!")
    return texto


def enlace_whatsapp(r, hoy=None):
    if not r.whatsapp:
        return ""
    return f"https://wa.me/{r.whatsapp}?text={quote(mensaje(r, hoy))}"


def resumen_dia(fecha):
    qs = del_dia(fecha)
    vigentes = [r for r in qs if r.estado != Reserva.Estado.CANCELADA]
    return {
        "n": len(vigentes),
        "personas": sum(r.personas for r in vigentes),
        "por_confirmar": sum(1 for r in qs if r.estado == Reserva.Estado.PENDIENTE),
        "llegaron": sum(1 for r in qs if r.estado == Reserva.Estado.LLEGO),
        "no_vino": sum(1 for r in qs if r.estado == Reserva.Estado.NO_VINO),
    }
