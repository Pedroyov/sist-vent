"""
Lógica de la programación del año: feriados, plan de estudios, jornada,
horario (con detección de cruces) y copia de un año a otro.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Sum

from core.models import AnioLectivo, DiaNoLectivo, Grado, Nivel, Periodo, Seccion

from .models import Asignacion, Bloque, Clase, HorasPlan

# --- Feriados nacionales (D. Leg. 713 y leyes posteriores: 16 feriados) -------


def _pascua(anio):
    """Domingo de Pascua (algoritmo de Butcher)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(anio, mes, dia)


def feriados_peru(anio):
    pascua = _pascua(anio)
    return [
        (date(anio, 1, 1), "Año Nuevo"),
        (pascua - timedelta(days=3), "Jueves Santo"),
        (pascua - timedelta(days=2), "Viernes Santo"),
        (date(anio, 5, 1), "Día del Trabajo"),
        (date(anio, 6, 7), "Batalla de Arica y Día de la Bandera"),
        (date(anio, 6, 29), "San Pedro y San Pablo"),
        (date(anio, 7, 23), "Día de la Fuerza Aérea del Perú"),
        (date(anio, 7, 28), "Fiestas Patrias"),
        (date(anio, 7, 29), "Fiestas Patrias"),
        (date(anio, 8, 6), "Batalla de Junín"),
        (date(anio, 8, 30), "Santa Rosa de Lima"),
        (date(anio, 10, 8), "Combate de Angamos"),
        (date(anio, 11, 1), "Todos los Santos"),
        (date(anio, 12, 8), "Inmaculada Concepción"),
        (date(anio, 12, 9), "Batalla de Ayacucho"),
        (date(anio, 12, 25), "Navidad"),
    ]


def cargar_feriados(anio: AnioLectivo):
    """Agrega los feriados nacionales del año que caen de lunes a viernes y aún no están."""
    existentes = set(DiaNoLectivo.objects.filter(anio_lectivo=anio).values_list("fecha", flat=True))
    nuevos = [
        DiaNoLectivo(anio_lectivo=anio, fecha=f, motivo=m, tipo=DiaNoLectivo.Tipo.FERIADO)
        for f, m in feriados_peru(anio.anio)
        if f not in existentes and f.weekday() < 5
    ]
    DiaNoLectivo.objects.bulk_create(nuevos)
    return len(nuevos)


def dias_lectivos(anio, desde=None, hasta=None):
    """Lista de días de clase (lunes a viernes, sin días no lectivos) en el rango."""
    desde = max(desde or anio.fecha_inicio, anio.fecha_inicio)
    hasta = min(hasta or anio.fecha_fin, anio.fecha_fin)
    no = DiaNoLectivo.mapa(anio, desde, hasta)
    dias, f = [], desde
    while f <= hasta:
        if f.weekday() < 5 and f not in no:
            dias.append(f)
        f += timedelta(days=1)
    return dias


# --- Plan de estudios -------------------------------------------------------

# Horas semanales sugeridas (referenciales: el colegio las ajusta a su plan).
HORAS_SUGERIDAS = {
    "Primaria": {"MAT": 5, "COM": 5, "ING": 2, "PS": 3, "AYC": 3, "CYT": 3, "EF": 3, "ER": 2},
    "Secundaria": {"MAT": 5, "COM": 5, "ING": 3, "AYC": 2, "CCSS": 3, "DPCC": 3, "EF": 2, "ER": 2, "CYT": 4, "EPT": 3},
}


def horas_plan(anio):
    """{(grado_id, curso_id): horas}"""
    return {(h.grado_id, h.curso_id): h.horas for h in HorasPlan.objects.filter(anio_lectivo=anio)}


# --- Jornada ----------------------------------------------------------------

def _mas(t, minutos):
    return (datetime.combine(date.today(), t) + timedelta(minutes=minutos)).time()


@transaction.atomic
def generar_bloques(anio, nivel, inicio: time, duracion: int, n_horas: int, recreos: list[tuple[int, int]]):
    """Reemplaza la jornada del nivel. recreos: [(después de la hora N, minutos)]."""
    if Clase.objects.filter(bloque__anio_lectivo=anio, bloque__nivel=nivel).exists():
        raise ValueError("Esta jornada ya se usa en horarios. Vacía primero esos horarios o edita los bloques uno por uno.")
    Bloque.objects.filter(anio_lectivo=anio, nivel=nivel).delete()
    recreo_tras = dict(recreos)
    t, orden = inicio, 1
    for h in range(1, n_horas + 1):
        fin = _mas(t, duracion)
        Bloque.objects.create(anio_lectivo=anio, nivel=nivel, orden=orden, inicio=t, fin=fin, tipo=Bloque.Tipo.CLASE)
        t, orden = fin, orden + 1
        if h in recreo_tras and h < n_horas:
            fin = _mas(t, recreo_tras[h])
            Bloque.objects.create(anio_lectivo=anio, nivel=nivel, orden=orden, inicio=t, fin=fin, tipo=Bloque.Tipo.RECREO)
            t, orden = fin, orden + 1


# --- Horario y cruces -------------------------------------------------------

def clases_de_docente(docente, anio, excluir_seccion=None):
    qs = Clase.objects.filter(asignacion__docente=docente, seccion__anio_lectivo=anio).select_related(
        "bloque", "seccion__grado", "asignacion__curso")
    if excluir_seccion is not None:
        qs = qs.exclude(seccion=excluir_seccion)
    return list(qs)


def ocupacion_docentes(anio, docentes, excluir_seccion=None):
    """{docente_id: [(dia, bloque, texto)]} para saber dónde está cada docente."""
    qs = Clase.objects.filter(seccion__anio_lectivo=anio, asignacion__docente__in=docentes).select_related(
        "bloque", "seccion__grado", "asignacion__curso")
    if excluir_seccion is not None:
        qs = qs.exclude(seccion=excluir_seccion)
    res = defaultdict(list)
    for c in qs:
        res[c.asignacion.docente_id].append((c.dia, c.bloque, f"{c.asignacion.curso.corto} {c.seccion.grado.nombre} {c.seccion.nombre}"))
    return res


def cruce(ocupacion, docente_id, dia, bloque):
    """Texto de la clase que choca, o None."""
    for d, b, texto in ocupacion.get(docente_id, []):
        if d == dia and b.se_cruza_con(bloque):
            return texto
    return None


def cruces_del_anio(anio):
    """Lista de choques: un docente en dos aulas a la misma hora."""
    clases = list(Clase.objects.filter(seccion__anio_lectivo=anio, asignacion__docente__isnull=False).select_related(
        "bloque", "seccion__grado", "asignacion__curso", "asignacion__docente"))
    por_docente_dia = defaultdict(list)
    for c in clases:
        por_docente_dia[(c.asignacion.docente_id, c.dia)].append(c)
    choques = []
    for lista in por_docente_dia.values():
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if a.bloque.se_cruza_con(b.bloque):
                    choques.append((a, b))
    return choques


# --- Estado de la programación (para el panel) -------------------------------

def estado(anio):
    secciones = Seccion.objects.filter(anio_lectivo=anio)
    n_secc = secciones.count()
    asign = Asignacion.objects.filter(seccion__anio_lectivo=anio)
    plan = HorasPlan.objects.filter(anio_lectivo=anio, horas__gt=0)
    grados_con_secc = Grado.objects.filter(secciones__anio_lectivo=anio).distinct()
    niveles_con_secc = Nivel.objects.filter(grados__secciones__anio_lectivo=anio).distinct()
    clases = Clase.objects.filter(seccion__anio_lectivo=anio).count()
    horas_necesarias = 0
    hp = horas_plan(anio)
    for a in asign.select_related("seccion"):
        horas_necesarias += hp.get((a.seccion.grado_id, a.curso_id), 0)
    return {
        "periodos": Periodo.objects.filter(anio_lectivo=anio).count(),
        "no_lectivos": DiaNoLectivo.objects.filter(anio_lectivo=anio).count(),
        "secciones": n_secc,
        "plan_grados": plan.values("grado").distinct().count(),
        "grados": grados_con_secc.count(),
        "sin_tutor": secciones.filter(tutor__isnull=True).count(),
        "asignaciones": asign.count(),
        "sin_docente": asign.filter(docente__isnull=True).count(),
        "secciones_sin_cursos": secciones.annotate(n=Count("asignaciones")).filter(n=0).count(),
        "jornadas": Bloque.objects.filter(anio_lectivo=anio).values("nivel").distinct().count(),
        "niveles": niveles_con_secc.count(),
        "clases": clases,
        "horas_necesarias": horas_necesarias,
        "cruces": len(cruces_del_anio(anio)),
        "dias_lectivos": len(dias_lectivos(anio)),
    }


# --- Copiar programación ----------------------------------------------------

def _mover(fecha, anios):
    try:
        return fecha.replace(year=fecha.year + anios)
    except ValueError:  # 29 de febrero
        return fecha.replace(year=fecha.year + anios, day=28)


@transaction.atomic
def copiar(origen: AnioLectivo, destino: AnioLectivo, que: set):
    """Copia lo marcado de un año a otro sin duplicar. que ⊆ {periodos, calendario, secciones, plan, docentes, jornada, horario}"""
    salto = destino.anio - origen.anio
    r = defaultdict(int)
    if "periodos" in que and not destino.periodos.exists():
        for p in origen.periodos.all():
            Periodo.objects.create(anio_lectivo=destino, numero=p.numero, nombre=p.nombre,
                                   fecha_inicio=_mover(p.fecha_inicio, salto), fecha_fin=_mover(p.fecha_fin, salto))
            r["periodos"] += 1
    if "calendario" in que:
        existentes = set(destino.dias_no_lectivos.values_list("fecha", flat=True))
        for d in origen.dias_no_lectivos.exclude(tipo=DiaNoLectivo.Tipo.FERIADO):  # los feriados se recalculan
            f = _mover(d.fecha, salto)
            if f not in existentes:
                DiaNoLectivo.objects.create(anio_lectivo=destino, fecha=f, motivo=d.motivo, tipo=d.tipo,
                                            fecha_fin=_mover(d.fecha_fin, salto) if d.fecha_fin else None)
                r["calendario"] += 1
        r["calendario"] += cargar_feriados(destino)
    mapa_secc = {}
    if que & {"secciones", "docentes", "horario"}:
        for s in origen.secciones.all():
            nueva, creada = Seccion.objects.get_or_create(
                anio_lectivo=destino, grado=s.grado, nombre=s.nombre,
                defaults={"turno": s.turno, "vacantes": s.vacantes, "tutor": s.tutor, "modo_asistencia": s.modo_asistencia},
            )
            mapa_secc[s.pk] = nueva
            r["secciones"] += creada
    if "plan" in que:
        for h in HorasPlan.objects.filter(anio_lectivo=origen):
            _, creada = HorasPlan.objects.get_or_create(anio_lectivo=destino, grado=h.grado, curso=h.curso, defaults={"horas": h.horas})
            r["plan"] += creada
    mapa_asig = {}
    if que & {"docentes", "horario"}:
        for a in Asignacion.objects.filter(seccion__anio_lectivo=origen):
            nueva, creada = Asignacion.objects.get_or_create(
                seccion=mapa_secc[a.seccion_id], curso=a.curso, defaults={"docente": a.docente})
            mapa_asig[a.pk] = nueva
            r["docentes"] += creada
    mapa_bloq = {}
    if que & {"jornada", "horario"}:
        for b in Bloque.objects.filter(anio_lectivo=origen):
            nuevo = Bloque.objects.filter(anio_lectivo=destino, nivel=b.nivel, orden=b.orden).first()
            if nuevo is None:
                nuevo = Bloque.objects.create(anio_lectivo=destino, nivel=b.nivel, orden=b.orden,
                                              inicio=b.inicio, fin=b.fin, tipo=b.tipo)
                r["jornada"] += 1
            mapa_bloq[b.pk] = nuevo
    if "horario" in que:
        for c in Clase.objects.filter(seccion__anio_lectivo=origen):
            _, creada = Clase.objects.get_or_create(
                seccion=mapa_secc[c.seccion_id], dia=c.dia, bloque=mapa_bloq[c.bloque_id],
                defaults={"asignacion": mapa_asig[c.asignacion_id]})
            r["horario"] += creada
    return dict(r)


def resumen_carga(anio):
    """Horas por docente: según plan (asignadas) y ubicadas en el horario."""
    hp = horas_plan(anio)
    carga = defaultdict(lambda: {"plan": 0, "horario": 0, "minutos": 0})
    for a in Asignacion.objects.filter(seccion__anio_lectivo=anio, docente__isnull=False).select_related("seccion"):
        carga[a.docente_id]["plan"] += hp.get((a.seccion.grado_id, a.curso_id), 0)
    for c in Clase.objects.filter(seccion__anio_lectivo=anio, asignacion__docente__isnull=False).select_related("bloque", "asignacion"):
        carga[c.asignacion.docente_id]["horario"] += 1
        carga[c.asignacion.docente_id]["minutos"] += c.bloque.minutos
    return carga


def total_horas(qs):
    return qs.aggregate(t=Sum("horas"))["t"] or 0


def control_carga(anio):
    """Revisión por docente: horas que le tocan (plan), ubicadas en el horario, máximo de contrato y cruces."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    carga = resumen_carga(anio)
    cruces = defaultdict(list)
    for a, b in cruces_del_anio(anio):
        cruces[a.asignacion.docente_id].append((a, b))
    por_dia = defaultdict(lambda: defaultdict(int))
    for c in Clase.objects.filter(seccion__anio_lectivo=anio, asignacion__docente__isnull=False).select_related("asignacion"):
        por_dia[c.asignacion.docente_id][c.dia] += 1
    ids = set(carga) | set(Seccion.objects.filter(anio_lectivo=anio, tutor__isnull=False).values_list("tutor_id", flat=True))
    filas = []
    for u in User.objects.filter(pk__in=ids).select_related("trabajador").order_by("first_name", "last_name", "username"):
        c = carga.get(u.pk, {"plan": 0, "horario": 0, "minutos": 0})
        t = getattr(u, "trabajador", None)
        maximo = t.horas_max_semana if t else None
        problemas = []
        if maximo is not None and c["plan"] > maximo:
            problemas.append(f"Tiene {c['plan']} h asignadas y su máximo es {maximo} h")
        if maximo is not None and c["horario"] > maximo:
            problemas.append(f"Su horario suma {c['horario']} h y su máximo es {maximo} h")
        if cruces.get(u.pk):
            problemas.append(f"{len(cruces[u.pk])} cruce{'s' if len(cruces[u.pk]) != 1 else ''} de horario")
        avisos = []
        if c["horario"] < c["plan"]:
            avisos.append(f"Faltan ubicar {c['plan'] - c['horario']} h en el horario")
        elif c["horario"] > c["plan"]:
            avisos.append(f"Tiene {c['horario'] - c['plan']} h más en el horario que en el plan")
        if t is None:
            avisos.append("Sin ficha de personal (no se conoce su máximo)")
        elif maximo is None:
            avisos.append("Sin máximo de horas definido")
        filas.append({
            "docente": u, "trabajador": t, "plan": c["plan"], "horario": c["horario"], "maximo": maximo,
            "horas_reloj": round(c["minutos"] / 60, 1), "cruces": cruces.get(u.pk, []),
            "dias": [por_dia[u.pk].get(d, 0) for d in range(1, 6)],
            "problemas": problemas, "avisos": avisos,
            "pct": min(100, round(100 * c["plan"] / maximo)) if maximo else None,
        })
    filas.sort(key=lambda f: (not f["problemas"], not f["avisos"], (f["docente"].get_full_name() or f["docente"].username).lower()))
    return filas
