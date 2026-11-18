"""Lógica de reservas: crear y editar (con aviso de choques), estados, llegada a la mesa y mensajes de WhatsApp."""
from datetime import date, datetime, time, timedelta
from core.utils import enlace_whatsapp as _enlace_wa

from django.db import transaction
from django.utils import timezone

from core import turnos
from core.turnos import dia_texto, hora_texto  # noqa: F401  (se usan desde aquí)

from .models import Config, Reserva


class ReservaError(Exception):
    pass


def _limpio(texto, largo):
    return " ".join(str(texto or "").split())[:largo]


def _telefono(texto):
    return "".join(c for c in str(texto or "") if c.isdigit() or c == "+")[:20]


def _mesa_activa():
    from core.permisos import modulos_activos

    return "mesas" in modulos_activos()


def choques(fecha, hora, mesa, excluir=None, cfg=None):
    """Otras reservas activas que usan esa mesa (como principal o juntada) y se cruzan con esta (según la duración)."""
    from django.db.models import Q

    if mesa is None:
        return []
    cfg = cfg or Config.cargar()
    inicio = datetime.combine(fecha, hora)
    dur = timedelta(minutes=cfg.duracion)
    qs = Reserva.objects.filter(Q(mesa=mesa) | Q(mesas_extra=mesa), fecha=fecha, estado__in=Reserva.ACTIVAS).distinct()
    if excluir is not None and excluir.pk:
        qs = qs.exclude(pk=excluir.pk)
    return [r for r in qs if abs(datetime.combine(r.fecha, r.hora) - inicio) < dur]


def _recordar_cliente(r):
    """El cliente por su celular, igual que en todo el sistema (clientes.servicios.recordar)."""
    from clientes.servicios import recordar

    r.cliente = recordar(r.nombre, r.telefono, origen="reservas", cliente=r.cliente if r.cliente_id else None)


def guardar(usuario, reserva=None, *, fecha, hora, personas, nombre, telefono="", mesa=None, mesas=None, nota="", permitir_choque=False):
    """Crea o edita una reserva. Devuelve (reserva, avisos). Si alguna mesa ya está reservada a esa hora, pide confirmar.
    `mesas`: una o varias (grupos grandes); la primera es la principal. `mesa` sirve para una sola."""
    mesas = [m for m in (mesas if mesas is not None else [mesa]) if m is not None]
    mesas = list(dict.fromkeys(mesas))  # sin repetidas, en orden
    mesa = mesas[0] if mesas else None
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
    for x in mesas:
        if not x.activa:
            raise ReservaError(f"La mesa {x.nombre} está desactivada.")
    cfg = Config.cargar()
    if not permitir_choque:
        for x in mesas:
            cruce = choques(fecha, hora, x, excluir=reserva, cfg=cfg)
            if cruce:
                otra = cruce[0]
                raise ReservaError(f"La mesa {x.nombre} ya está reservada a las {otra.hora:%H:%M} ({otra.nombre}, {otra.personas} pers.). "
                                   "Elige otra mesa, o confirma si igual quieres reservarla.")
    avisos = []
    capacidad = sum(x.capacidad for x in mesas)
    if mesas and personas > capacidad:
        nombres = " + ".join(x.nombre for x in mesas)
        avisos.append(f"{'La mesa' if len(mesas) == 1 else 'Las mesas'} {nombres} {'es' if len(mesas) == 1 else 'son'} para {capacidad}: "
                      "quizá haya que juntar otra.")
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
        r.mesas_extra.set(mesas[1:])
    return r, avisos


def _estado(r, usuario, estado, desde=Reserva.ACTIVAS):
    return turnos.cambiar_estado(r, usuario, estado, desde, ReservaError)


def confirmar(r, usuario):
    return _estado(r, usuario, Reserva.Estado.CONFIRMADA, desde=(Reserva.Estado.PENDIENTE,))


def cancelar(r, usuario):
    return _estado(r, usuario, Reserva.Estado.CANCELADA)


def no_vino(r, usuario):
    return _estado(r, usuario, Reserva.Estado.NO_VINO)


def reabrir(r, usuario):
    """Deshacer «No vino» o «Cancelada» (por ejemplo, llegaron tarde o se marcó por error)."""
    return _estado(r, usuario, Reserva.Estado.CONFIRMADA, desde=(Reserva.Estado.NO_VINO, Reserva.Estado.CANCELADA))


def llego(r, usuario, mesa=None, mesas=None):
    """Llegaron: abre la cuenta en la primera mesa y junta las demás (grupos grandes), con las personas de la reserva.
    Sin indicar mesas, usa las de la reserva. Las juntadas que ya estén ocupadas se saltan (con aviso en r.aviso).
    Sin el módulo Mesas, solo marca la reserva como «Llegó». Devuelve la cuenta abierta (o None)."""
    if not r.activa:
        raise ReservaError(f"La reserva ya está como «{r.get_estado_display()}».")
    mesas = [x for x in (mesas if mesas else ([mesa] if mesa else r.mesas)) if x is not None]
    mesas = list(dict.fromkeys(mesas))
    mesa = mesas[0] if mesas else None
    r.aviso = ""
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
            otras = mesas[1:]
            if otras:
                from mesas.models import Cuenta, Mesa

                ocupadas = set(Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA, mesa__in=otras).values_list("mesa_id", flat=True))
                ocupadas |= set(Mesa.objects.filter(pk__in=[x.pk for x in otras], unida_a__estado=Cuenta.Estado.ABIERTA)
                                .exclude(unida_a=cuenta).values_list("pk", flat=True))
                libres = [x for x in otras if x.pk not in ocupadas]
                if libres:
                    from mesas.servicios import unir_mesas

                    unir_mesas(cuenta, libres)
                if ocupadas:
                    r.aviso = "Ocupada" + ("s" if len(ocupadas) > 1 else "") + ": mesa " + ", ".join(x.nombre for x in otras if x.pk in ocupadas) + \
                        ". Júntala cuando se libere (Juntar o cambiar mesa)."
        r.mesa = mesa or r.mesa
        r.cuenta = cuenta
        r.estado, r.cambiada_por, r.cambiada_en = Reserva.Estado.LLEGO, usuario, timezone.now()
        r.save(update_fields=["mesa", "cuenta", "estado", "cambiada_por", "cambiada_en"])
        if mesas:
            r.mesas_extra.set(mesas[1:])
    return cuenta


def cerrar_pasadas(hoy=None):
    """Las reservas de días anteriores que siguen activas quedan como «No vino» (nadie las marcó)."""
    return turnos.cerrar_pasadas(Reserva, hoy)


def del_dia(fecha):
    return Reserva.objects.filter(fecha=fecha).select_related("mesa", "creada_por", "cuenta").prefetch_related("mesas_extra")


def para_mapa(ahora=None, cfg=None):
    """{mesa_id: reserva} de las mesas que deben verse como reservadas ahora (desde `antes` hasta la tolerancia)."""
    ahora = ahora or timezone.now()
    cfg = cfg or Config.cargar()
    local = timezone.localtime(ahora)
    resultado = {}
    qs = Reserva.objects.filter(fecha=local.date(), estado__in=Reserva.ACTIVAS, mesa__isnull=False).prefetch_related("mesas_extra")
    for r in qs.select_related("mesa").order_by("hora"):
        m = r.momento
        if m - timedelta(minutes=cfg.antes) <= ahora <= m + timedelta(minutes=cfg.tolerancia):
            for x in r.mesas:
                resultado.setdefault(x.pk, r)
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


def mensaje(r, hoy=None):
    """Texto para WhatsApp: confirmación (si es otro día) o recordatorio (si es hoy)."""
    negocio = turnos.negocio()
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
    return _enlace_wa(r.telefono, mensaje(r, hoy))


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
