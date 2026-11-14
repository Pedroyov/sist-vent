"""
Horas trabajadas y pago estimado de cada trabajador.

- Clases: según el horario de clases (cada bloque = 1 hora pedagógica), solo en días lectivos.
- Horario propio: horario semanal fuera de clases; se cuenta todos los días de ese tipo del mes,
  menos los feriados.
- Otras horas: horas semanales adicionales, proporcionales a las semanas lectivas del mes.

Es una ESTIMACIÓN: no incluye descuentos ni aportes de ley (ONP/AFP, EsSalud, renta), gratificaciones ni CTS.
"""
import calendar
from collections import Counter
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from academico.models import Clase
from academico.programacion import dias_lectivos
from core.models import DiaNoLectivo

from .models import Trabajador

CERO = Decimal("0")


def _d(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rango_mes(mes: date):
    return mes.replace(day=1), date(mes.year, mes.month, calendar.monthrange(mes.year, mes.month)[1])


def clases_por_dia(trabajador, anio):
    """{dia_semana(1-5): (n_horas_pedagogicas, minutos)}"""
    res = {}
    if not trabajador.usuario_id or anio is None:
        return res
    for c in Clase.objects.filter(asignacion__docente_id=trabajador.usuario_id, seccion__anio_lectivo=anio).select_related("bloque"):
        n, m = res.get(c.dia, (0, 0))
        res[c.dia] = (n + 1, m + c.bloque.minutos)
    return res


def semana(trabajador, anio):
    clases = clases_por_dia(trabajador, anio)
    n_clases = sum(n for n, _ in clases.values())
    min_clases = sum(m for _, m in clases.values())
    propias = sum((h.horas for h in trabajador.horarios.all()), CERO)
    total = _d(Decimal(min_clases) / 60 + propias + trabajador.horas_extra_semana)
    return {
        "clases": n_clases, "horas_clase": _d(Decimal(min_clases) / 60),
        "horario_propio": _d(propias), "extra": trabajador.horas_extra_semana, "total": total,
    }


def mes(trabajador, anio, mes_fecha):
    desde, hasta = rango_mes(mes_fecha)
    # clases en días lectivos del mes
    lectivos = dias_lectivos(anio, desde, hasta) if anio else []
    por_dia = Counter(d.isoweekday() for d in lectivos)
    clases = clases_por_dia(trabajador, anio)
    n_clases = sum(clases.get(d, (0, 0))[0] * k for d, k in por_dia.items())
    min_clases = sum(clases.get(d, (0, 0))[1] * k for d, k in por_dia.items())
    # horario propio: todos los días del mes de ese tipo, menos feriados
    feriados = set(DiaNoLectivo.mapa(anio, desde, hasta, solo_feriados=True)) if anio else set()
    horas_dia = Counter()
    for h in trabajador.horarios.all():
        horas_dia[h.dia] += h.horas
    propias, f = CERO, desde
    while f <= hasta:
        if f not in feriados:
            propias += horas_dia.get(f.isoweekday(), CERO)
        f += timedelta(days=1)
    # otras horas: proporcional a las semanas con clases
    semanas = Decimal(len(lectivos)) / 5
    extra = trabajador.horas_extra_semana * semanas
    horas_reloj = _d(Decimal(min_clases) / 60 + propias + extra)

    if trabajador.modalidad == Trabajador.Modalidad.MENSUAL:
        pago = _d(trabajador.sueldo)
        detalle = "Sueldo mensual fijo"
    else:
        pago = _d(trabajador.pago_hora * (Decimal(n_clases) + propias + extra))
        partes = []
        if n_clases:
            partes.append(f"{n_clases} h de clase")
        if propias:
            partes.append(f"{_d(propias)} h de horario")
        if extra:
            partes.append(f"{_d(extra)} h adicionales")
        detalle = (" + ".join(partes) or "0 h") + f" × S/ {trabajador.pago_hora}"
    return {
        "desde": desde, "hasta": hasta, "dias_lectivos": len(lectivos),
        "clases": n_clases, "horas_clase": _d(Decimal(min_clases) / 60),
        "horario_propio": _d(propias), "extra": _d(extra), "horas": horas_reloj,
        "pago": pago, "detalle": detalle,
    }
