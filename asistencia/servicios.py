"""Reglas de la asistencia: quién puede tomarla, a quién se lista y cómo se resume el día."""
from collections import defaultdict

from django.db.models import Q

from academico.models import Asignacion
from alumnos.models import Matricula
from core.models import ModoAsistencia, Seccion
from core.permisos import puede

from .models import Asistencia, Estado, Sesion


def es_direccion(user):
    """Puede tomar y ver la asistencia de todas las secciones."""
    return puede(user, "asistencia.todas")


def puede_tomar(user, seccion, asignacion=None):
    if es_direccion(user):
        return True
    if not puede(user, "asistencia.tomar"):
        return False
    if asignacion is not None:
        return asignacion.docente_id == user.pk
    return seccion.tutor_id == user.pk


def alumnos_de(seccion, fecha):
    """Matriculados en la sección en esa fecha (incluye a quien se retiró después de esa fecha)."""
    mats = (
        Matricula.objects.filter(seccion=seccion)
        .filter(Q(estado=Matricula.Estado.MATRICULADO) | Q(fecha_retiro__gt=fecha))
        .filter(fecha__lte=fecha)
        .select_related("alumno")
        .order_by("alumno__apellido_paterno", "alumno__apellido_materno", "alumno__nombres")
    )
    return [m.alumno for m in mats]


def mis_clases(user, anio, fecha):
    """Lo que el usuario debe tomar en la fecha: secciones diarias y cursos (por curso)."""
    if anio is None:
        return [], []
    secciones = Seccion.objects.filter(anio_lectivo=anio, modo_asistencia=ModoAsistencia.DIARIA)
    asignaciones = Asignacion.objects.filter(
        seccion__anio_lectivo=anio, seccion__modo_asistencia=ModoAsistencia.POR_CURSO, curso__activo=True
    )
    if not es_direccion(user):
        secciones = secciones.filter(tutor=user)
        asignaciones = asignaciones.filter(docente=user)
    secciones = list(secciones.select_related("grado__nivel").order_by("grado__nivel__orden", "grado__orden", "nombre"))
    asignaciones = list(asignaciones.select_related("seccion__grado__nivel", "curso", "docente").order_by(
        "seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre", "curso__orden"))

    sesiones = Sesion.objects.filter(fecha=fecha).filter(
        Q(seccion__in=secciones, asignacion__isnull=True) | Q(asignacion__in=asignaciones)
    ).prefetch_related("registros")
    por_seccion = {s.seccion_id: s for s in sesiones if s.asignacion_id is None}
    por_asig = {s.asignacion_id: s for s in sesiones if s.asignacion_id}
    for s in secciones:
        s.sesion = por_seccion.get(s.pk)
        s.conteo = _conteo(s.sesion)
    for a in asignaciones:
        a.sesion = por_asig.get(a.pk)
        a.conteo = _conteo(a.sesion)
    _ordenar_por_horario(asignaciones, fecha)
    return secciones, asignaciones


def _ordenar_por_horario(asignaciones, fecha):
    """Marca a qué hora toca cada curso ese día (según el horario) y los ordena; 'ahora' si está en curso."""
    from django.utils import timezone

    from academico.models import Clase

    dia = fecha.isoweekday()
    horas = {}
    if dia <= 5 and asignaciones:
        for c in Clase.objects.filter(asignacion__in=asignaciones, dia=dia).select_related("bloque").order_by("bloque__inicio"):
            horas.setdefault(c.asignacion_id, []).append(c.bloque)
    ahora = timezone.localtime().time() if fecha == timezone.localdate() else None
    con_horario = set(Clase.objects.filter(asignacion__in=asignaciones).values_list("seccion_id", flat=True).distinct()) if asignaciones else set()
    for a in asignaciones:
        a.bloques_hoy = horas.get(a.pk, [])
        # si la sección tiene horario, solo toca tomar los cursos que hay ese día
        a.toca_hoy = bool(a.bloques_hoy) or a.seccion_id not in con_horario
        a.hora = a.bloques_hoy[0].inicio if a.bloques_hoy else None
        a.ahora = bool(ahora and any(b.inicio <= ahora < b.fin for b in a.bloques_hoy))
    asignaciones.sort(key=lambda a: (not a.ahora, a.hora is None, a.hora or 0))


def motivo_no_lectivo(anio, fecha):
    from core.models import DiaNoLectivo

    if anio and not (anio.fecha_inicio <= fecha <= anio.fecha_fin):
        return "Fuera del año escolar"
    return DiaNoLectivo.motivo_de(anio, fecha) or ("Fin de semana" if fecha.weekday() >= 5 else None)


def pendientes(anio, fecha, secciones, asignaciones):
    if motivo_no_lectivo(anio, fecha):
        return 0
    return sum(1 for s in secciones if not s.sesion) + sum(1 for a in asignaciones if a.toca_hoy and not a.sesion)


def _conteo(sesion):
    if sesion is None:
        return None
    c = {e: 0 for e in Estado.values}
    for r in sesion.registros.all():
        c[r.estado] += 1
    return c


def combinar(estados):
    """Estado del día a partir de las clases del día (asistencia por curso)."""
    if not estados:
        return None
    if Estado.PRESENTE in estados or Estado.TARDE in estados:
        return Estado.TARDE if Estado.TARDE in estados and Estado.PRESENTE not in estados else Estado.PRESENTE
    if Estado.JUSTIFICADA in estados:
        return Estado.JUSTIFICADA
    return Estado.FALTA


def estados_por_dia(seccion, desde, hasta, asignacion=None):
    """{(alumno_id, fecha): estado} en el rango. Si la sección es por curso y no se indica
    curso, combina todas las clases del día."""
    regs = Asistencia.objects.filter(sesion__seccion=seccion, sesion__fecha__range=(desde, hasta))
    if asignacion is not None:
        regs = regs.filter(sesion__asignacion=asignacion)
    elif not seccion.por_curso:
        regs = regs.filter(sesion__asignacion__isnull=True)
    juntos = defaultdict(list)
    for alumno_id, fecha, estado in regs.values_list("alumno_id", "sesion__fecha", "estado"):
        juntos[(alumno_id, fecha)].append(estado)
    return {k: (v[0] if len(v) == 1 else combinar(v)) for k, v in juntos.items()}


def resumen_alumno(alumno, anio):
    """Totales del año para la ficha del alumno (por día)."""
    mat = alumno.matricula_en(anio)
    if mat is None:
        return None
    sec = mat.seccion
    estados = estados_por_dia(sec, anio.fecha_inicio, anio.fecha_fin)
    dias = {f: e for (a, f), e in estados.items() if a == alumno.pk}
    tot = {e: 0 for e in Estado.values}
    for e in dias.values():
        tot[e] += 1
    n = len(dias)
    return {
        "dias": n, "P": tot["P"], "T": tot["T"], "F": tot["F"], "J": tot["J"],
        "porcentaje": round(100 * (tot["P"] + tot["T"]) / n) if n else None,
        "ultimas_faltas": sorted((f for f, e in dias.items() if e in ("F", "J")), reverse=True)[:5],
    }
