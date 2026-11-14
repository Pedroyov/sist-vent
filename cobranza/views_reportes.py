"""Morosos (con recordatorio por WhatsApp) y exportaciones a Excel."""
from datetime import date
from urllib.parse import quote

from django.utils.http import content_disposition_header
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from alumnos.models import Alumno, AlumnoApoderado, Matricula
from alumnos.utils import filtro_en, opciones_en
from core.colegio import nombre as colegio_nombre
from core.excel import a_bytes
from core.models import AnioLectivo
from core.permisos import permiso_requerido

from .models import CERO, MENSAJE_RECORDATORIO, Cargo, ConfigCobranza, Pago, Recordatorio

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Seguro(dict):
    """Para .format_map: si el mensaje tiene una variable desconocida, la deja tal cual."""

    def __missing__(self, clave):
        return "{" + clave + "}"


def _mensaje(plantilla, apoderado, alumno, cargos, total):
    detalle = "\n".join(f"• {c.concepto}: S/ {c.saldo}" for c in cargos)
    nombre_apo = f"{apoderado.nombres.title()}" if apoderado else "apoderado(a)"
    return (plantilla or MENSAJE_RECORDATORIO).format_map(_Seguro(
        apoderado=nombre_apo, alumno=alumno.nombres.title(), detalle=detalle,
        total=total, colegio=colegio_nombre(),
    ))


def calcular_morosos(anio, en="", minimo=1, hoy=None):
    """Lista de alumnos con deuda vencida, con sus cuotas, apoderado y último aviso."""
    hoy = hoy or timezone.localdate()
    config = ConfigCobranza.objects.filter(anio_lectivo=anio).first()
    cargos = (
        Cargo.objects.vencidos(hoy).filter(concepto__anio_lectivo=anio)
        .select_related("concepto").order_by("vencimiento")
    )
    mats = Matricula.objects.filter(anio_lectivo=anio).select_related("seccion__grado__nivel")
    if en:
        mats_filtradas = mats.filter(filtro_en(en))
        cargos = cargos.filter(alumno_id__in=mats_filtradas.values("alumno_id"))
    por_alumno = {}
    for c in cargos:
        por_alumno.setdefault(c.alumno_id, []).append(c)
    por_alumno = {k: v for k, v in por_alumno.items() if len(v) >= minimo}

    alumnos = {a.pk: a for a in Alumno.objects.filter(pk__in=por_alumno)}
    mat_de = {m.alumno_id: m for m in mats.filter(alumno_id__in=por_alumno)}
    apo_de = {}
    for v in AlumnoApoderado.objects.filter(alumno_id__in=por_alumno).select_related("apoderado").order_by("-responsable_pago", "id"):
        apo_de.setdefault(v.alumno_id, v.apoderado)
    aviso_de = {}
    for r in Recordatorio.objects.filter(anio_lectivo=anio, alumno_id__in=por_alumno).order_by("-fecha"):
        aviso_de.setdefault(r.alumno_id, r)

    filas = []
    for alumno_id, lista in por_alumno.items():
        alumno = alumnos[alumno_id]
        apo = apo_de.get(alumno_id)
        total = sum((c.saldo for c in lista), CERO)
        mora = sum((c.mora(config, hoy) for c in lista), CERO)
        texto = _mensaje(config.mensaje_recordatorio if config else None, apo, alumno, lista, total)
        filas.append({
            "alumno": alumno, "mat": mat_de.get(alumno_id), "cargos": lista, "total": total, "mora": mora,
            "apoderado": apo, "aviso": aviso_de.get(alumno_id), "mas_antigua": lista[0].vencimiento,
            "wa": f"https://wa.me/{apo.whatsapp}?text={quote(texto)}" if apo and apo.whatsapp else None,
        })
    return filas


def _ordenar(filas, orden):
    if orden == "monto":
        filas.sort(key=lambda f: (-f["total"], f["alumno"].apellido_paterno))
    elif orden == "antiguedad":
        filas.sort(key=lambda f: (f["mas_antigua"], f["alumno"].apellido_paterno))
    else:  # por sección
        filas.sort(key=lambda f: (
            (f["mat"].seccion.grado.nivel.orden, f["mat"].seccion.grado.orden, f["mat"].seccion.nombre) if f["mat"] else (99, 99, ""),
            f["alumno"].apellido_paterno, f["alumno"].apellido_materno, f["alumno"].nombres,
        ))
    return filas


@permiso_requerido("cobranza.ver")
def morosos(request):
    anio = AnioLectivo.actual()
    if anio is None:
        return redirect("core:inicio")
    en = request.GET.get("en", "")
    minimo = request.GET.get("min", "1")
    minimo = int(minimo) if minimo.isdigit() and int(minimo) > 0 else 1
    orden = request.GET.get("orden", "seccion")
    filas = _ordenar(calcular_morosos(anio, en, minimo), orden)
    if request.GET.get("excel"):
        return _morosos_excel(filas, anio)
    return render(request, "cobranza/morosos.html", {
        "anio": anio, "filas": filas, "opciones_en": opciones_en(anio),
        "f": {"en": en, "min": minimo, "orden": orden},
        "total": sum((f["total"] for f in filas), CERO),
        "sin_whatsapp": sum(1 for f in filas if not f["wa"]),
        "hoy": timezone.localdate(),
        "query": request.GET.urlencode(),
    })


@permiso_requerido("cobranza.ver")
@require_POST
def registrar_aviso(request, alumno_pk):
    """Se llama (por HTMX) al pulsar el botón de WhatsApp en la lista de morosos."""
    alumno = get_object_or_404(Alumno, pk=alumno_pk)
    anio = AnioLectivo.actual()
    monto = sum((c.saldo for c in Cargo.objects.vencidos().filter(alumno=alumno, concepto__anio_lectivo=anio)), CERO)
    r = Recordatorio.objects.create(alumno=alumno, anio_lectivo=anio, monto=monto, usuario=request.user)
    return render(request, "cobranza/partials/aviso.html", {"aviso": r, "hoy": timezone.localdate()})


# --- Excel ------------------------------------------------------------------

def _hoja(titulo, encabezados, anchos):
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    for i, (h, w) in enumerate(zip(encabezados, anchos), start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0D6EFD")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return wb, ws


def _respuesta(wb, nombre):
    resp = HttpResponse(a_bytes(wb), content_type=XLSX)
    resp["Content-Disposition"] = content_disposition_header(True, nombre)
    return resp


def _morosos_excel(filas, anio):
    wb, ws = _hoja(
        f"Morosos {anio}",
        ["Alumno", "DNI", "Nivel", "Grado", "Sección", "Cuotas vencidas", "Detalle", "Total vencido (S/)",
         "Apoderado", "Celular", "Último aviso"],
        [32, 11, 11, 11, 8, 9, 45, 12, 30, 12, 14],
    )
    for f in filas:
        m = f["mat"]
        ws.append([
            f["alumno"].nombre_completo, f["alumno"].numero_documento,
            m.seccion.grado.nivel.nombre if m else "", m.seccion.grado.nombre if m else "", m.seccion.nombre if m else "",
            len(f["cargos"]), ", ".join(str(c.concepto) for c in f["cargos"]), float(f["total"]),
            f"{f['apoderado'].apellidos}, {f['apoderado'].nombres}" if f["apoderado"] else "",
            f["apoderado"].celular if f["apoderado"] else "",
            timezone.localtime(f["aviso"].fecha).strftime("%d/%m/%Y") if f["aviso"] else "",
        ])
    for celda in ws["H"][1:]:
        celda.number_format = "#,##0.00"
    ws.auto_filter.ref = ws.dimensions
    return _respuesta(wb, f"morosos_{anio}_{timezone.localdate():%Y%m%d}.xlsx")


@permiso_requerido("cobranza.ver")
def pagos_excel(request):
    hoy = timezone.localdate()
    try:
        desde = date.fromisoformat(request.GET.get("desde", ""))
    except ValueError:
        desde = hoy
    try:
        hasta = date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        hasta = desde
    if hasta < desde:
        desde, hasta = hasta, desde
    pagos = (
        Pago.objects.filter(fecha__range=(desde, hasta))
        .select_related("alumno", "registrado_por").prefetch_related("detalles__cargo__concepto")
        .order_by("fecha", "numero")
    )
    wb, ws = _hoja(
        "Pagos",
        ["Fecha", "Recibo", "Alumno", "DNI", "Conceptos", "Método", "N° operación", "Total (S/)", "Estado", "Registrado por"],
        [11, 14, 32, 11, 40, 13, 14, 11, 10, 18],
    )
    for p in pagos:
        ws.append([
            p.fecha.strftime("%d/%m/%Y"), p.numero_texto, p.alumno.nombre_completo, p.alumno.numero_documento,
            ", ".join(str(d.cargo.concepto) for d in p.detalles.all()), p.get_metodo_display(), p.numero_operacion,
            float(p.total), "Anulado" if p.anulado else "Válido",
            p.registrado_por.get_full_name() or p.registrado_por.username,
        ])
    for celda in ws["H"][1:]:
        celda.number_format = "#,##0.00"
    ws.auto_filter.ref = ws.dimensions
    return _respuesta(wb, f"pagos_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx")
