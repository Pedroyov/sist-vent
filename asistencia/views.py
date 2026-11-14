import calendar
from datetime import date, timedelta
from urllib.parse import quote

from django.utils.http import content_disposition_header
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from academico.models import Asignacion
from alumnos.models import Alumno, AlumnoApoderado
from core.colegio import nombre as colegio_nombre
from core.excel import a_bytes
from core.models import AnioLectivo, DiaNoLectivo, Seccion
from core.permisos import permiso_requerido, puede

from . import servicios
from .models import Asistencia, AvisoFalta, Estado, Sesion

DIAS_ATRAS_DOCENTE = 7  # cuántos días atrás puede corregir un docente
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _fecha(request, user):
    hoy = timezone.localdate()
    try:
        f = date.fromisoformat(request.GET.get("fecha") or request.POST.get("fecha") or "")
    except ValueError:
        f = hoy
    if f > hoy:
        f = hoy
    if not servicios.es_direccion(user) and f < hoy - timedelta(days=DIAS_ATRAS_DOCENTE):
        f = hoy - timedelta(days=DIAS_ATRAS_DOCENTE)
    return f


@permiso_requerido("asistencia.tomar", "asistencia.todas")
def hoy(request):
    anio = AnioLectivo.actual()
    fecha = _fecha(request, request.user)
    secciones, asignaciones = servicios.mis_clases(request.user, anio, fecha)
    pendientes = servicios.pendientes(anio, fecha, secciones, asignaciones)
    return render(request, "asistencia/hoy.html", {
        "anio": anio, "fecha": fecha, "hoy": timezone.localdate(),
        "no_lectivo": servicios.motivo_no_lectivo(anio, fecha),
        "otros_cursos": [a for a in asignaciones if not a.toca_hoy],
        "hay_horario": any(a.bloques_hoy for a in asignaciones),
        "ayer": fecha - timedelta(days=1), "manana": fecha + timedelta(days=1),
        "secciones": secciones, "asignaciones": asignaciones, "pendientes": pendientes,
        "es_dir": servicios.es_direccion(request.user), "ver_resumen": puede(request.user, "asistencia.reportes"),
        "dia": DIAS[fecha.weekday()],
    })


@permiso_requerido("asistencia.tomar", "asistencia.todas")
def tomar(request, seccion_pk, asignacion_pk=None):
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=seccion_pk)
    asignacion = get_object_or_404(Asignacion.objects.select_related("curso"), pk=asignacion_pk, seccion=seccion) if asignacion_pk else None
    if not servicios.puede_tomar(request.user, seccion, asignacion):
        raise PermissionDenied
    fecha = _fecha(request, request.user)
    alumnos = servicios.alumnos_de(seccion, fecha)
    sesion = Sesion.objects.filter(seccion=seccion, fecha=fecha, asignacion=asignacion).first()
    previos = {r.alumno_id: r for r in sesion.registros.all()} if sesion else {}

    if request.method == "POST":
        conteo = {e: 0 for e in Estado.values}
        with transaction.atomic():
            if sesion is None:
                sesion = Sesion.objects.create(seccion=seccion, fecha=fecha, asignacion=asignacion, tomado_por=request.user)
            else:
                sesion.tomado_por = request.user
                sesion.save(update_fields=["tomado_por", "actualizado"])
            for a in alumnos:
                estado = request.POST.get(f"e_{a.pk}", Estado.PRESENTE)
                if estado not in Estado.values:
                    estado = Estado.PRESENTE
                obs = request.POST.get(f"o_{a.pk}", "").strip()[:200]
                Asistencia.objects.update_or_create(sesion=sesion, alumno=a, defaults={"estado": estado, "observacion": obs})
                conteo[estado] += 1
        partes = [f"{conteo['P']} presentes"]
        if conteo["T"]:
            partes.append(f"{conteo['T']} tardanza{'s' if conteo['T'] > 1 else ''}")
        if conteo["F"]:
            partes.append(f"{conteo['F']} falta{'s' if conteo['F'] > 1 else ''}")
        if conteo["J"]:
            partes.append(f"{conteo['J']} justificada{'s' if conteo['J'] > 1 else ''}")
        que = f"{asignacion.curso} · " if asignacion else ""
        messages.success(request, f"Asistencia guardada ({que}{seccion.grado.nombre} {seccion.nombre}): " + ", ".join(partes) + ".")
        return redirect(f"{reverse('asistencia:hoy')}?fecha={fecha.isoformat()}")

    for a in alumnos:
        r = previos.get(a.pk)
        a.estado = r.estado if r else Estado.PRESENTE
        a.obs = r.observacion if r else ""
    return render(request, "asistencia/tomar.html", {
        "seccion": seccion, "asignacion": asignacion, "fecha": fecha, "alumnos": alumnos, "sesion": sesion,
        "estados": Estado.choices, "dia": DIAS[fecha.weekday()],
    })


# --- Resumen del día (Dirección) --------------------------------------------

@permiso_requerido("asistencia.reportes")
def resumen(request):
    anio = AnioLectivo.actual()
    fecha = _fecha(request, request.user)
    secciones = list(
        Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel", "tutor")
        .order_by("grado__nivel__orden", "grado__orden", "nombre")
    ) if anio else []
    sesiones = Sesion.objects.filter(fecha=fecha, seccion__in=secciones).select_related("asignacion")
    tomadas = {}
    for s in sesiones:
        tomadas.setdefault(s.seccion_id, []).append(s)
    n_cursos = {}
    for a in Asignacion.objects.filter(seccion__in=secciones, curso__activo=True).values_list("seccion_id", flat=True):
        n_cursos[a] = n_cursos.get(a, 0) + 1

    faltaron, total_alumnos, presentes, sin_tomar = [], 0, 0, 0
    for sec in secciones:
        sec.sesiones = tomadas.get(sec.pk, [])
        sec.n_cursos = n_cursos.get(sec.pk, 0)
        estados = servicios.estados_por_dia(sec, fecha, fecha)
        sec.conteo = {e: 0 for e in Estado.values}
        for (alumno_id, _), e in estados.items():
            sec.conteo[e] += 1
            if e in (Estado.FALTA, Estado.JUSTIFICADA):
                faltaron.append((alumno_id, sec, e))
        sec.tomada = bool(sec.sesiones)
        if sec.tomada:
            total_alumnos += len(estados)
            presentes += sec.conteo["P"] + sec.conteo["T"]
        else:
            sin_tomar += 1

    # datos de los que faltaron + WhatsApp
    alumnos = {a.pk: a for a in Alumno.objects.filter(pk__in=[f[0] for f in faltaron])}
    apo = {}
    for v in AlumnoApoderado.objects.filter(alumno_id__in=alumnos).select_related("apoderado").order_by("-responsable_pago", "id"):
        apo.setdefault(v.alumno_id, v.apoderado)
    avisados = set(AvisoFalta.objects.filter(fecha=fecha, alumno_id__in=alumnos).values_list("alumno_id", flat=True))
    lista = []
    for alumno_id, sec, e in faltaron:
        a, ap = alumnos[alumno_id], apo.get(alumno_id)
        texto = (
            f"Estimado(a) {ap.nombres.title() if ap else 'apoderado(a)'}, le informamos que "
            f"{a.nombres.title()} no asistió hoy {fecha:%d/%m/%Y} a clases en {colegio_nombre()}. "
            "Si hubo algún motivo, por favor comuníquelo al tutor(a). Gracias."
        )
        lista.append({
            "alumno": a, "seccion": sec, "estado": e, "apoderado": ap, "avisado": alumno_id in avisados,
            "wa": f"https://wa.me/{ap.whatsapp}?text={quote(texto)}" if ap and ap.whatsapp else None,
        })
    return render(request, "asistencia/resumen.html", {
        "no_lectivo": DiaNoLectivo.motivo_de(anio, fecha) or ("Fin de semana" if fecha.weekday() >= 5 else None),
        "fecha": fecha, "hoy": timezone.localdate(), "ayer": fecha - timedelta(days=1), "manana": fecha + timedelta(days=1),
        "secciones": secciones, "faltaron": lista, "sin_tomar": sin_tomar,
        "porcentaje": round(100 * presentes / total_alumnos) if total_alumnos else None,
        "dia": DIAS[fecha.weekday()],
    })


@permiso_requerido("asistencia.reportes")
@require_POST
def avisar_falta(request, alumno_pk):
    alumno = get_object_or_404(Alumno, pk=alumno_pk)
    fecha = _fecha(request, request.user)
    AvisoFalta.objects.create(alumno=alumno, fecha=fecha, usuario=request.user)
    return HttpResponse('<span class="small text-success"><i class="bi bi-check2-all"></i> Avisado</span>')


# --- Reporte mensual por sección --------------------------------------------

def _secciones_visibles(user, anio):
    qs = Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre")
    if puede(user, "asistencia.todas", "asistencia.reportes"):
        return qs
    return qs.filter(pk__in=list(user.tutorias.values_list("pk", flat=True)) + list(
        user.asignaciones.values_list("seccion_id", flat=True)))


@permiso_requerido("asistencia.tomar", "asistencia.todas", "asistencia.reportes")
def reporte(request):
    anio = AnioLectivo.actual()
    secciones = list(_secciones_visibles(request.user, anio)) if anio else []
    if not secciones:
        messages.info(request, "No tienes secciones asignadas.")
        return redirect("asistencia:hoy")
    sec_id = request.GET.get("seccion", "")
    seccion = next((s for s in secciones if str(s.pk) == sec_id), secciones[0])
    hoy = timezone.localdate()
    try:
        y, m = map(int, request.GET.get("mes", "").split("-"))
        mes = date(y, m, 1)
    except ValueError:
        mes = hoy.replace(day=1)
    fin = date(mes.year, mes.month, calendar.monthrange(mes.year, mes.month)[1])

    cursos = list(seccion.asignaciones.select_related("curso").filter(curso__activo=True)) if seccion.por_curso else []
    asig_id = request.GET.get("curso", "")
    asignacion = next((a for a in cursos if str(a.pk) == asig_id), None)
    if asignacion and not puede(request.user, "asistencia.todas", "asistencia.reportes") and asignacion.docente_id != request.user.pk and seccion.tutor_id != request.user.pk:
        raise PermissionDenied

    estados = servicios.estados_por_dia(seccion, mes, fin, asignacion)
    dias = sorted({f for (_, f) in estados})
    alumnos = servicios.alumnos_de(seccion, fin if fin <= hoy else hoy)
    vistos = {a.pk for a in alumnos}
    extra = Alumno.objects.filter(pk__in={a for (a, _) in estados} - vistos)  # retirados con registros en el mes
    alumnos += list(extra)
    filas = []
    for a in alumnos:
        celdas = [estados.get((a.pk, d)) for d in dias]
        tot = {e: celdas.count(e) for e in Estado.values}
        n = sum(tot.values())
        filas.append({"alumno": a, "celdas": celdas, "tot": tot,
                      "pct": round(100 * (tot["P"] + tot["T"]) / n) if n else None})

    if request.GET.get("excel"):
        return _reporte_excel(seccion, asignacion, mes, dias, filas)
    anterior = (mes - timedelta(days=1)).replace(day=1)
    siguiente = (fin + timedelta(days=1))
    return render(request, "asistencia/reporte.html", {
        "secciones": secciones, "seccion": seccion, "cursos": cursos, "asignacion": asignacion,
        "mes": mes, "dias": [(d, DIAS[d.weekday()][0]) for d in dias], "filas": filas,
        "anterior": anterior, "siguiente": siguiente if siguiente <= hoy else None,
        "query": request.GET.urlencode(),
    })


COLORES = {"P": "D1E7DD", "T": "FFF3CD", "F": "F8D7DA", "J": "CFE2FF"}


def _reporte_excel(seccion, asignacion, mes, dias, filas):
    wb = Workbook()
    ws = wb.active
    ws.title = f"{mes:%m-%Y}"
    titulo = f"Asistencia {seccion.grado.nombre} «{seccion.nombre}» {seccion.grado.nivel}"
    if asignacion:
        titulo += f" – {asignacion.curso}"
    ws["A1"] = f"{titulo} – {mes:%m/%Y}"
    ws["A1"].font = Font(bold=True, size=12)
    enc = ["Alumno"] + [d.strftime("%d") for d in dias] + ["P", "T", "F", "J", "%"]
    ws.append([])
    ws.append(enc)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
    for f in filas:
        ws.append([f["alumno"].nombre_completo] + [x or "" for x in f["celdas"]]
                  + [f["tot"]["P"], f["tot"]["T"], f["tot"]["F"], f["tot"]["J"], f["pct"] if f["pct"] is not None else ""])
        fila = ws.max_row
        for i, x in enumerate(f["celdas"], start=2):
            if x:
                c = ws.cell(row=fila, column=i)
                c.fill = PatternFill("solid", fgColor=COLORES[x])
                c.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 34
    for i in range(2, len(enc) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 4.5
    ws.freeze_panes = "B4"
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(
        True, f"asistencia_{seccion.grado.nombre}_{seccion.nombre}_{mes:%Y%m}.xlsx".replace(" ", "_"))
    return resp
