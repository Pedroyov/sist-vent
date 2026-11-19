"""Horarios libres, citas y mensajes.

Todo se calcula en minutos desde las 00:00 del día. Los horarios libres de un profesional en un día son su jornada
(entrada a salida) menos el refrigerio, menos sus ausencias, menos sus citas (por confirmar, confirmadas y atendidas)
y, si es hoy, menos lo que ya pasó.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta
from core.utils import enlace_whatsapp

from django.db import transaction
from django.utils import timezone

from personal.models import Persona

from core import turnos
from core.turnos import dia_corto, dia_texto, hora_texto  # noqa: F401  (se usan desde aquí)

from .models import Ausencia, Cita, Config, Horario


class CitaError(Exception):
    pass


# --- Minutos ------------------------------------------------------------------------------

def m(t):
    return t.hour * 60 + t.minute


def a_hora(minutos):
    minutos = max(0, min(int(minutos), 24 * 60 - 1))
    return time(minutos // 60, minutos % 60)


def _restar(rangos, quitar):
    """Rangos [(a, b)] menos un rango (x, y)."""
    x, y = quitar
    salida = []
    for a, b in rangos:
        if y <= a or x >= b:
            salida.append((a, b))
            continue
        if x > a:
            salida.append((a, x))
        if y < b:
            salida.append((y, b))
    return salida


# --- Jornada y horarios libres ------------------------------------------------------------

class Dia:
    """Datos de un día ya cargados (horarios, ausencias y citas de todos), para no consultar por cada hueco."""

    def __init__(self, fecha, excluir=None):
        self.fecha = fecha
        self.horarios = {h.profesional_id: h for h in Horario.objects.filter(dia=fecha.weekday())}
        self.ausencias = {}
        for a in Ausencia.objects.filter(desde__lte=fecha, hasta__gte=fecha):
            self.ausencias.setdefault(a.profesional_id, []).append(a)
        self.citas = {}
        qs = Cita.objects.filter(fecha=fecha, estado__in=Cita.OCUPAN)
        if excluir is not None and getattr(excluir, "pk", None):
            qs = qs.exclude(pk=excluir.pk)
        for c in qs:
            self.citas.setdefault(c.profesional_id, []).append(c)

    def jornada(self, prof):
        """Rangos en que trabaja ese día (sin el refrigerio ni las ausencias). [] = no trabaja."""
        h = self.horarios.get(prof.pk)
        if h is None or m(h.salida) <= m(h.entrada):
            return []
        rangos = [(m(h.entrada), m(h.salida))]
        if h.descanso_desde and h.descanso_hasta and m(h.descanso_hasta) > m(h.descanso_desde):
            rangos = _restar(rangos, (m(h.descanso_desde), m(h.descanso_hasta)))
        for a in self.ausencias.get(prof.pk, []):
            if a.todo_el_dia:
                return []
            rangos = _restar(rangos, (m(a.hora_desde), m(a.hora_hasta)))
        return rangos

    def ausencia(self, prof):
        """La ausencia de todo el día (para decir «Vacaciones», «Día libre»)."""
        return next((a for a in self.ausencias.get(prof.pk, []) if a.todo_el_dia), None)

    def libres(self, prof, ahora=None):
        """Rangos libres: jornada − citas − lo que ya pasó (si es hoy)."""
        rangos = self.jornada(prof)
        ahora = timezone.localtime(ahora or timezone.now())
        es_hoy = self.fecha == timezone.localdate()
        for c in self.citas.get(prof.pk, []):
            fin = m(c.fin)
            if c.estado == Cita.Estado.EN_ATENCION and es_hoy:  # se pasó del tiempo: sigue ocupada hasta que toquen «Terminar»
                fin = max(fin, _minuto(timezone.localtime()) + 5)
            rangos = _restar(rangos, (m(c.inicio), fin))
        if self.fecha == ahora.date():
            rangos = _restar(rangos, (0, ahora.hour * 60 + ahora.minute))
        elif self.fecha < ahora.date():
            return []
        return [(a, b) for a, b in rangos if b > a]

    def horarios_libres(self, prof, duracion, intervalo, ahora=None):
        """Horas de inicio posibles (minutos) para un servicio de esa duración."""
        salida = []
        for a, b in self.libres(prof, ahora):
            t = -(-a // intervalo) * intervalo  # redondea hacia arriba al intervalo
            while t + duracion <= b:
                salida.append(t)
                t += intervalo
        return salida

    def cabe(self, prof, inicio, fin, ahora=None):
        return any(a <= inicio and fin <= b for a, b in self.libres(prof, ahora))


def profesionales(servicio=None):
    """Los activos que hacen ese servicio (una Variante o un Producto)."""
    pid = getattr(servicio, "producto_id", None) or getattr(servicio, "pk", None) if servicio is not None else None
    return [p for p in Persona.objects.filter(activo=True, atiende_citas=True).prefetch_related("servicios") if p.hace(pid)]


def duracion_de(variante, cfg=None):
    cfg = cfg or Config.cargar()
    return (variante.producto.duracion_min if variante is not None and variante.producto.duracion_min else None) or cfg.duracion


def proximos(prof, duracion, desde, desde_min=0, n=6, por_dia=3, dias=21, cfg=None, excluir=None):
    """Los próximos horarios libres de un profesional desde un día y hora: [(fecha, minutos)], máximo `por_dia` por día."""
    cfg = cfg or Config.cargar()
    salida = []
    for i in range(dias):
        f = desde + timedelta(days=i)
        horas = [t for t in Dia(f, excluir).horarios_libres(prof, duracion, cfg.intervalo) if i or t >= desde_min]
        salida += [(f, t) for t in horas[:por_dia]]
        if len(salida) >= n:
            break
    return salida[:n]


def a_esa_hora(fecha, inicio, duracion, servicio=None, sin=None, cfg=None, excluir=None):
    """Otros profesionales que pueden atender a esa hora o poco después (hasta 1 hora): [(profesional, minutos)]."""
    cfg = cfg or Config.cargar()
    dia = Dia(fecha, excluir)
    salida = []
    for p in profesionales(servicio):
        if sin is not None and p.pk == sin.pk:
            continue
        t = next((t for t in dia.horarios_libres(p, duracion, cfg.intervalo) if inicio <= t <= inicio + 60), None)
        if t is not None:
            salida.append((p, t))
    return sorted(salida, key=lambda x: x[1])


# --- Clientes -----------------------------------------------------------------------------

def _recordar_cliente(c):
    """El cliente por su celular, igual que en todo el sistema (clientes.servicios.recordar)."""
    from clientes.servicios import recordar

    c.cliente = recordar(c.nombre, c.telefono, origen="citas", cliente=c.cliente if c.cliente_id else None)


# --- Agendar ------------------------------------------------------------------------------

def _limpio(texto, largo):
    return " ".join(str(texto or "").split())[:largo]


def agendar(usuario, cita=None, *, profesional, fecha, inicio, duracion, servicio=None, nombre, telefono="", nota="", forzar=False):
    """Crea o cambia una cita. Revisa que el profesional esté libre (salvo `forzar`, para quien gestiona la agenda)."""
    nombre = _limpio(nombre, 60)
    if not nombre:
        raise CitaError("Escribe el nombre del cliente.")
    if profesional is None:
        raise CitaError("Elige quién atiende.")
    if not isinstance(fecha, date) or not isinstance(inicio, time):
        raise CitaError("Elige el día y la hora.")
    try:
        duracion = int(duracion)
    except (TypeError, ValueError):
        raise CitaError("Indica cuánto dura.")
    if not 5 <= duracion <= 600:
        raise CitaError("La duración no es válida.")
    if not profesional.activo:
        raise CitaError(f"{profesional.nombre} ya no está activo.")
    if servicio is not None and not profesional.hace(servicio.producto_id):
        raise CitaError(f"{profesional.nombre} no hace «{servicio.producto.nombre}».")
    ini = m(inicio)
    fin = ini + duracion
    if fin > 24 * 60:
        raise CitaError("La cita termina después de la medianoche.")
    nueva = cita is None
    if nueva and timezone.make_aware(datetime.combine(fecha, inicio)) < timezone.now() - timedelta(minutes=30):
        raise CitaError("Esa fecha y hora ya pasaron.")
    if cita is not None and not cita.activa:
        raise CitaError("Esta cita ya se cerró: no se puede cambiar.")
    if not forzar and not Dia(fecha, cita).cabe(profesional, ini, fin, ahora=timezone.now() - timedelta(minutes=30)):
        raise CitaError(f"{profesional.nombre} no está libre {dia_texto(fecha)} a las {hora_texto(inicio)} por {duracion} minutos.")
    c = cita or Cita(creada_por=usuario)
    if not nueva:
        c.cambiada_por, c.cambiada_en = usuario, timezone.now()
    c.fecha, c.inicio, c.fin, c.profesional = fecha, a_hora(ini), a_hora(fin), profesional
    c.servicio = servicio
    c.servicio_nombre = servicio.nombre_completo[:120] if servicio is not None else (c.servicio_nombre if not nueva else "")
    c.precio = servicio.precio_venta if servicio is not None else None
    c.nombre, c.telefono, c.nota = nombre, "".join(ch for ch in str(telefono or "") if ch.isdigit() or ch == "+")[:20], _limpio(nota, 200)
    with transaction.atomic():
        _recordar_cliente(c)
        c.save()
    return c


def _estado(c, usuario, estado, desde=Cita.ACTIVAS):
    return turnos.cambiar_estado(c, usuario, estado, desde, CitaError)


def confirmar(c, usuario):
    return _estado(c, usuario, Cita.Estado.CONFIRMADA, desde=(Cita.Estado.PENDIENTE,))


def atender(c, usuario):
    """Atendida: pasa a «Por cobrar» en caja (con la duración agendada). Si estaba en atención, es «Terminar»."""
    if c.estado == Cita.Estado.EN_ATENCION:
        terminar(c, usuario)
        c.refresh_from_db()
        return c
    return _estado(c, usuario, Cita.Estado.ATENDIDA)


def _minuto(momento):
    return momento.hour * 60 + momento.minute


def empezar(c, usuario):
    """El cliente de una cita se sentó: queda «En atención» desde ahora, con la duración agendada como estimado.
    Ocupa a la persona hasta que toquen «Terminar» (aunque se pase)."""
    hoy = timezone.localdate()
    if c.fecha != hoy:
        raise CitaError("Solo se empieza el mismo día de la cita.")
    ahora = _minuto(timezone.localtime())
    duracion = max(c.minutos, 5)
    _estado(c, usuario, Cita.Estado.EN_ATENCION)
    c.inicio, c.fin = a_hora(ahora), a_hora(min(ahora + duracion, 24 * 60 - 1))
    c.save(update_fields=["inicio", "fin"])
    return c


def de_la_atencion(c):
    """Todo lo que está en atención en el mismo registro que `c` (la cita y lo «algo más», o los servicios de un cliente sin cita)."""
    from django.db.models import Q

    clave = clave_cuenta(c)
    return list(Cita.objects.filter(Q(cuenta=clave) | Q(pk=clave), estado=Cita.Estado.EN_ATENCION).order_by("inicio", "pk"))


def terminar(c, usuario):
    """Terminó: se guarda la hora real de fin y pasa a «Por cobrar». Si en esa atención hubo varios servicios seguidos,
    el tiempo real se reparte entre ellos según lo que dura cada uno. Devuelve los servicios terminados."""
    citas = de_la_atencion(c)
    if not citas:
        raise CitaError("Esa atención ya terminó.")
    ahora = timezone.localtime()
    real = citas[0].fecha == ahora.date()
    if real:
        desde = m(citas[0].inicio)
        total = max(1, _minuto(ahora) - desde)
        estimado = sum(x.minutos for x in citas) or 1
        t = desde
        for i, x in enumerate(citas):
            dur = total - (t - desde) if i == len(citas) - 1 else max(1, round(x.minutos * total / estimado))
            x.inicio, x.fin = a_hora(t), a_hora(min(t + dur, 24 * 60 - 1))
            t += dur
    with transaction.atomic():
        for x in citas:
            x.estado, x.tiempo_real = Cita.Estado.ATENDIDA, real
            x.cambiada_por, x.cambiada_en = usuario, timezone.now()
            x.save(update_fields=["estado", "tiempo_real", "inicio", "fin", "cambiada_por", "cambiada_en"])
    return citas


def no_vino(c, usuario):
    return _estado(c, usuario, Cita.Estado.NO_VINO)


def cancelar(c, usuario):
    return _estado(c, usuario, Cita.Estado.CANCELADA)


def reabrir(c, usuario):
    """Deshacer «No vino», «Cancelada» o «Atendida» (marcada por error). Si ya ocuparon ese horario, avisa."""
    if c.cobrada:
        raise CitaError("Este servicio ya se cobró: no se puede volver a activar.")
    if c.estado in (Cita.Estado.NO_VINO, Cita.Estado.CANCELADA) and not Dia(c.fecha, c).cabe(c.profesional, m(c.inicio), m(c.fin), ahora=c.momento):
        raise CitaError("Ese horario ya se ocupó con otra cita: cámbiala de hora.")
    return _estado(c, usuario, Cita.Estado.CONFIRMADA,
                   desde=(Cita.Estado.NO_VINO, Cita.Estado.CANCELADA, Cita.Estado.ATENDIDA, Cita.Estado.EN_ATENCION))


def cerrar_pasadas(hoy=None):
    """Las citas de días anteriores que nadie marcó quedan como «No vino»; lo que quedó «En atención» (nadie tocó Terminar)
    pasa a «Por cobrar» con el tiempo estimado."""
    Cita.objects.filter(fecha__lt=hoy or timezone.localdate(), estado=Cita.Estado.EN_ATENCION).update(
        estado=Cita.Estado.ATENDIDA, cambiada_en=timezone.now())
    return turnos.cerrar_pasadas(Cita, hoy)


_negocio = turnos.negocio


def mensaje_cita(c, hoy=None):
    hoy = hoy or timezone.localdate()
    serv = f" para {c.servicio_nombre}" if c.servicio_nombre else ""
    if c.fecha == hoy:
        return (f"Hola {c.nombre}, le recordamos su cita de hoy a las {hora_texto(c.inicio)}{serv} con {c.profesional.nombre} "
                f"en {_negocio()}. ¡La esperamos!")
    return (f"Hola {c.nombre}, le confirmamos su cita{serv} con {c.profesional.nombre} en {_negocio()}: {dia_texto(c.fecha, hoy)} "
            f"{c.fecha:%d/%m} a las {hora_texto(c.inicio)}. Si no puede venir, por favor avísenos. ¡La esperamos!")


def enlace_cita(c, hoy=None):
    if not c.whatsapp:
        return ""
    return enlace_whatsapp(c.telefono, mensaje_cita(c, hoy))


def rangos_texto(rangos):
    return " · ".join(f"{hora_texto(a)} a {hora_texto(b)}" for a, b in rangos)


def mis_horarios(prof, desde=None, dias=None, cfg=None):
    """[(fecha, [(a, b)])] con los rangos libres de al menos 30 minutos de los próximos días."""
    cfg = cfg or Config.cargar()
    desde = desde or timezone.localdate()
    salida = []
    for i in range(dias or cfg.dias_compartir):
        f = desde + timedelta(days=i)
        rangos = []
        for a, b in Dia(f).libres(prof):
            a = -(-a // cfg.intervalo) * cfg.intervalo
            if b - a >= 30:
                rangos.append((a, b))
        if rangos:
            salida.append((f, rangos))
    return salida


def mensaje_horarios(prof, desde=None, dias=None, cfg=None):
    hoy = timezone.localdate()
    lineas = [f"Hola, estos son mis horarios libres para atenderte en {_negocio()}:", ""]
    datos = mis_horarios(prof, desde, dias, cfg)
    if not datos:
        lineas.append("Por ahora no tengo horarios libres en los próximos días.")
    for f, rangos in datos:
        lineas.append(f"*{dia_corto(f, hoy)}:* {rangos_texto(rangos)}")
    lineas += ["", f"Escríbeme para separar tu cita. — {prof.nombre}"]
    return "\n".join(lineas)


def enlace_horarios(prof, cfg=None):
    return enlace_whatsapp(None, mensaje_horarios(prof, cfg=cfg))  # elige a quién mandarlo


def resumen_dia(fecha, prof=None):
    qs = Cita.objects.filter(fecha=fecha)
    if prof is not None:
        qs = qs.filter(profesional=prof)
    estados = Counter(qs.values_list("estado", flat=True))
    return {"n": sum(v for k, v in estados.items() if k != Cita.Estado.CANCELADA), "por_confirmar": estados[Cita.Estado.PENDIENTE],
            "atendidas": estados[Cita.Estado.ATENDIDA], "no_vino": estados[Cita.Estado.NO_VINO],
            "en_atencion": estados[Cita.Estado.EN_ATENCION]}


# --- Servicios hechos y cobro en caja ----------------------------------------------------

SIN_NOMBRE = "Cliente sin cita"  # quien llegó sin cita y no dio su nombre


def registrar_servicios(usuario, profesional, servicios, nombre="", telefono="", nota="", cita=None, *, empezar=False, empezo_hace=None):
    """Cliente sin cita (o algo más en una cita). Devuelve las citas creadas (una por servicio, una tras otra).
    - `empezar`: el cliente recién se sienta → «En atención» desde ahora; ocupa a la persona hasta «Terminar» (tiempo real).
    - si no, ya terminó → «Por cobrar»; empezó hace `empezo_hace` minutos o, si no se sabe, lo que duran los servicios
      (tiempo estimado). Lo «algo más» de una cita en atención sigue en atención con ella."""
    servicios = [s for s in servicios if s is not None]
    if profesional is None:
        raise CitaError("Elige quién atendió.")
    if not servicios:
        raise CitaError("Marca al menos un servicio.")
    cfg = Config.cargar()
    estado = Cita.Estado.ATENDIDA
    if cita is not None:
        nombre, telefono = cita.nombre, cita.telefono
        fecha, inicio = cita.fecha, m(cita.fin)
        if cita.estado == Cita.Estado.EN_ATENCION:
            estado = Cita.Estado.EN_ATENCION
    else:
        ahora = timezone.localtime()
        fecha = ahora.date()
        if empezar:
            inicio, estado = _minuto(ahora), Cita.Estado.EN_ATENCION
        else:
            hace = empezo_hace if empezo_hace else sum(duracion_de(s, cfg) for s in servicios)
            inicio = max(0, _minuto(ahora) - hace)  # se registra al terminar: empezó hace un rato
            inicio -= inicio % 5
    nombre = _limpio(nombre, 60) or SIN_NOMBRE
    creadas = []
    with transaction.atomic():
        for s in servicios:
            dur = duracion_de(s, cfg)
            fin = min(inicio + dur, 24 * 60 - 1)
            c = Cita(fecha=fecha, inicio=a_hora(inicio), fin=a_hora(fin), profesional=profesional, servicio=s,
                     servicio_nombre=s.nombre_completo[:120], precio=s.precio_venta, nombre=nombre,
                     telefono="".join(ch for ch in str(telefono or "") if ch.isdigit() or ch == "+")[:20], nota=_limpio(nota, 200),
                     estado=estado, sin_cita=cita is None, creada_por=usuario)
            if cita is not None and cita.cliente_id:
                c.cliente_id = cita.cliente_id
            else:
                _recordar_cliente(c)
            c.save()
            creadas.append(c)
            inicio = fin
        # lo de un mismo registro va en una sola cuenta (en una cita, se suma a la de esa cita)
        cuenta = (cita.cuenta or cita.pk) if cita is not None else creadas[0].pk
        Cita.objects.filter(pk__in=[c.pk for c in creadas]).update(cuenta=cuenta)
        for c in creadas:
            c.cuenta = cuenta
    return creadas


def clave_cuenta(c):
    """Con qué se agrupa en «Por cobrar»: su registro (o la cita sola)."""
    return c.cuenta or c.pk


def de_la_cuenta(cuenta):
    """Lo que falta cobrar de una tarjeta de «Por cobrar», en orden."""
    from django.db.models import Q

    return list(Cita.objects.filter(Q(cuenta=cuenta) | Q(pk=cuenta, cuenta__isnull=True), estado=Cita.Estado.ATENDIDA, cobrada=False)
                .select_related("profesional", "servicio__producto").order_by("fecha", "inicio", "pk"))


def se_puede_quitar(c):
    """Se quita lo que se registró en «Registrar servicio» (sin cita o «algo más»); la cita de la agenda se cambia desde la agenda."""
    return c.sin_cita or bool(c.cuenta and c.cuenta != c.pk)


def editar_cuenta(cuenta, usuario, nombre, telefono):
    """Pone el nombre y el celular a toda una tarjeta por cobrar (el cliente no se registró al llegar).
    Con el celular, el cliente queda registrado como en todo el sistema."""
    citas = de_la_cuenta(cuenta)
    if not citas:
        raise CitaError("Esa cuenta ya se cobró o ya no está.")
    nombre = _limpio(nombre, 60) or SIN_NOMBRE
    telefono = "".join(ch for ch in str(telefono or "") if ch.isdigit() or ch == "+")[:20]
    from clientes.servicios import recordar

    cliente = recordar(nombre, telefono, origen="citas", cliente=next((c.cliente for c in citas if c.cliente_id), None))
    ahora = timezone.now()
    with transaction.atomic():
        for c in citas:
            c.nombre, c.telefono, c.cliente = nombre, telefono, cliente
            c.cambiada_por, c.cambiada_en = usuario, ahora
            c.save(update_fields=["nombre", "telefono", "cliente", "cambiada_por", "cambiada_en"])
    return citas


def quitar_de_cuenta(cita, usuario):
    """Un servicio marcado por error, antes de cobrarlo: queda como cancelado (no se borra) y sale de «Por cobrar»."""
    if not (cita.por_cobrar or cita.en_atencion):
        raise CitaError("Ese servicio ya se cobró o ya no está por cobrar.")
    if not se_puede_quitar(cita):
        raise CitaError("Es la cita de la agenda: para quitarla, ábrela y usa «Volver a activar».")
    return turnos.cambiar_estado(cita, usuario, Cita.Estado.CANCELADA, (Cita.Estado.ATENDIDA, Cita.Estado.EN_ATENCION), CitaError)


def por_cobrar(desde_dias=7):
    """Servicios hechos que caja todavía no cobra, una tarjeta por registro (aunque sea el mismo cliente o «Cliente sin cita»):
    [{cuenta, nombre, telefono, citas, total, profesionales}]. Si paga uno por varios, caja los cobra juntos."""
    desde = timezone.localdate() - timedelta(days=desde_dias)
    return _por_registro(Cita.objects.filter(estado=Cita.Estado.ATENDIDA, cobrada=False, fecha__gte=desde))


def en_atencion_ahora(prof=None):
    """Lo que se está atendiendo ahora, una tarjeta por registro (para «Terminar»), con la hora estimada de fin."""
    qs = Cita.objects.filter(estado=Cita.Estado.EN_ATENCION, fecha=timezone.localdate())
    if prof is not None:
        qs = qs.filter(profesional=prof)
    grupos = _por_registro(qs)
    ahora = _minuto(timezone.localtime())
    for g in grupos:
        g["empezo"] = g["citas"][0].inicio
        g["pasado"] = ahora > m(g["desde"])  # ya se pasó del tiempo estimado
    return grupos


def _por_registro(qs):
    qs = qs.select_related("profesional", "servicio__producto").order_by("fecha", "inicio", "pk")
    grupos = {}
    for c in qs:
        clave = clave_cuenta(c)
        g = grupos.setdefault(clave, {"cuenta": clave, "fecha": c.fecha, "nombre": c.nombre, "telefono": c.telefono, "citas": []})
        g["citas"].append(c)
    salida = list(grupos.values())
    for g in salida:
        g["total"] = sum((c.servicio.precio_venta for c in g["citas"] if c.servicio_id), 0)
        g["ids"] = ",".join(str(c.pk) for c in g["citas"])
        g["profesionales"] = ", ".join(dict.fromkeys(c.profesional.nombre for c in g["citas"]))
        g["desde"] = g["citas"][-1].fin
    return salida


def contar_por_cobrar():
    return Cita.objects.filter(estado=Cita.Estado.ATENDIDA, cobrada=False, fecha__gte=timezone.localdate() - timedelta(days=7)).count()


def marcar_cobradas(ids, venta=None):
    """Al cobrar en Vender (o «ya se cobró aparte»): esos servicios salen de «Por cobrar».
    Con la venta, cada servicio guarda el precio al que se cobró (por si se cambió en caja) y, si en caja se eligió
    al cliente, los servicios que nadie identificó quedan a su nombre (así entran a su historial)."""
    citas = list(Cita.objects.filter(pk__in=list(ids), estado=Cita.Estado.ATENDIDA, cobrada=False))
    precios = {}
    cliente = venta.cliente if venta is not None and venta.cliente_id else None
    if venta is not None:
        for i in venta.items.all():
            precios.setdefault(i.variante_id, i.precio_unitario)
    for c in citas:
        c.cobrada, c.venta = True, venta
        campos = ["cobrada", "venta", "precio"]
        if c.servicio_id in precios:
            c.precio = precios[c.servicio_id]
        if cliente is not None and not c.cliente_id and c.nombre == SIN_NOMBRE:
            c.cliente, c.nombre, c.telefono = cliente, cliente.nombre[:60], c.telefono or cliente.telefono
            campos += ["cliente", "nombre", "telefono"]
        c.save(update_fields=campos)
    return len(citas)
