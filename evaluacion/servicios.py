"""Reglas de la evaluación: quién califica, qué se muestra en el registro y cómo se arma la libreta."""
from django.utils import timezone

from academico.models import Asignacion
from asistencia.servicios import alumnos_de, estados_por_dia
from core.permisos import puede


def es_direccion(user):
    """Ve y edita las notas de todas las secciones."""
    return puede(user, "notas.todas")
from core.models import Periodo

from .models import (
    LETRAS, Comentario, Conducta, ConfigEvaluacion, Escala, Nota, letra_final, promedio_vigesimal,
)


def periodo_actual(anio, hoy=None):
    hoy = hoy or timezone.localdate()
    periodos = list(Periodo.objects.filter(anio_lectivo=anio))
    for p in periodos:
        if p.fecha_inicio <= hoy <= p.fecha_fin:
            return p
    pasados = [p for p in periodos if p.fecha_inicio <= hoy]
    return pasados[-1] if pasados else (periodos[0] if periodos else None)


def puede_calificar(user, asignacion):
    return puede(user, "notas.todas") or asignacion.docente_id == user.pk


def puede_conducta(user, seccion):
    return puede(user, "notas.todas") or seccion.tutor_id == user.pk


def competencias_de(asignacion, config):
    if not config.por_competencia:
        return [None]
    comps = list(asignacion.curso.competencias.filter(activo=True))
    return comps or [None]


def alumnos_periodo(seccion, periodo):
    fecha = min(periodo.fecha_fin, timezone.localdate()) if periodo.fecha_inicio <= timezone.localdate() else periodo.fecha_inicio
    return alumnos_de(seccion, fecha) or alumnos_de(seccion, timezone.localdate())


def leer_valor(texto, config):
    """Convierte lo escrito por el docente. Devuelve (numero, letra, error)."""
    t = (texto or "").strip().upper()
    if not t:
        return None, "", None
    if config.vigesimal:
        if t.isdigit() and 0 <= int(t) <= 20:
            return int(t), "", None
        return None, "", f"«{texto}» no es una nota válida (0 a 20)"
    if t in LETRAS:
        return None, t, None
    return None, "", f"«{texto}» no es válido (AD, A, B o C)"


def esperadas_y_registradas(asignaciones, periodo):
    """{asignacion_id: (registradas, esperadas)} para el avance."""
    res = {}
    for a in asignaciones:
        config = ConfigEvaluacion.de(periodo.anio_lectivo, a.seccion.grado.nivel)
        n_comp = len(competencias_de(a, config))
        n_alumnos = len(alumnos_periodo(a.seccion, periodo))
        hechas = Nota.objects.filter(asignacion=a, periodo=periodo).exclude(numero__isnull=True, letra="").count()
        res[a.pk] = (hechas, n_alumnos * n_comp)
    return res


def libreta(alumno, anio):
    """Todo lo que va en la libreta de un alumno en un año."""
    mat = alumno.matricula_en(anio)
    if mat is None:
        return None
    seccion = mat.seccion
    config = ConfigEvaluacion.de(anio, seccion.grado.nivel)
    periodos = list(Periodo.objects.filter(anio_lectivo=anio))
    asignaciones = list(Asignacion.objects.filter(seccion=seccion, curso__activo=True).select_related("curso", "docente")
                        .order_by("curso__orden", "curso__nombre"))
    notas, conclusiones = {}, {}
    orden_periodo = {p.pk: i for i, p in enumerate(periodos)}
    for n in Nota.objects.filter(alumno=alumno, asignacion__in=asignaciones):
        notas[(n.asignacion_id, n.competencia_id, n.periodo_id)] = n.valor
        if n.conclusion:
            clave = (n.asignacion_id, n.competencia_id)
            if clave not in conclusiones or orden_periodo.get(n.periodo_id, 0) > conclusiones[clave][0]:
                conclusiones[clave] = (orden_periodo.get(n.periodo_id, 0), n.conclusion)
    comentarios = {}
    for c in Comentario.objects.filter(alumno=alumno, asignacion__in=asignaciones).select_related("periodo"):
        comentarios.setdefault(c.asignacion_id, []).append(c)

    cursos = []
    for a in asignaciones:
        comps = competencias_de(a, config)
        filas = []
        for comp in comps:
            valores = [notas.get((a.pk, comp.pk if comp else None, p.pk)) for p in periodos]
            final = promedio_vigesimal(valores) if config.vigesimal else letra_final(valores)
            filas.append({"competencia": comp, "valores": valores, "final": final,
                          "conclusion": conclusiones.get((a.pk, comp.pk if comp else None), (0, ""))[1]})
        area = None
        if config.vigesimal and comps != [None]:
            por_periodo = [promedio_vigesimal([f["valores"][i] for f in filas]) for i in range(len(periodos))]
            area = {"valores": por_periodo, "final": promedio_vigesimal(por_periodo)}
        elif comps == [None]:
            area = None  # la única fila ya es la nota del curso
        ultimo = sorted(comentarios.get(a.pk, []), key=lambda c: c.periodo.numero)
        cursos.append({"asignacion": a, "filas": filas, "area": area, "comentario": ultimo[-1] if ultimo else None})

    conducta = {c.periodo_id: c for c in Conducta.objects.filter(alumno=alumno, periodo__in=periodos)}
    asistencia = []
    for p in periodos:
        estados = estados_por_dia(seccion, p.fecha_inicio, p.fecha_fin)
        mios = [e for (a, f), e in estados.items() if a == alumno.pk]
        asistencia.append({"F": mios.count("F"), "J": mios.count("J"), "T": mios.count("T")})
    cond_vals = [conducta[p.pk].valor if p.pk in conducta else None for p in periodos]
    return {
        "alumno": alumno, "anio": anio, "matricula": mat, "seccion": seccion, "config": config,
        "periodos": periodos, "cursos": cursos,
        "conducta": [conducta.get(p.pk) for p in periodos],
        "conducta_final": (promedio_vigesimal(cond_vals) if config.vigesimal else letra_final(cond_vals)) if config.conducta else None,
        "asistencia": asistencia,
        "es_vigesimal": config.escala == Escala.VIGESIMAL,
    }
