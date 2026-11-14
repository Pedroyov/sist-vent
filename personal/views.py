from datetime import date, time
from decimal import Decimal

from django.utils.http import content_disposition_header
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from academico.models import DIAS_SEMANA
from academico.views_programacion import horario_de_docente
from core.excel import a_bytes
from core.models import AnioLectivo
from core.permisos import permiso_requerido

from . import calculo
from .forms import TrabajadorForm
from .models import DIAS_LABORALES, HorarioTrabajador, Trabajador

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _mes(request):
    hoy = timezone.localdate()
    try:
        y, m = map(int, request.GET.get("mes", "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return hoy.replace(day=1)


def _anio_de(mes):
    """Año lectivo que corresponde al mes elegido (o el actual)."""
    return AnioLectivo.objects.filter(anio=mes.year).first() or AnioLectivo.actual()


# --- Lista ------------------------------------------------------------------

@permiso_requerido("personal.ver")
def lista(request):
    mes = _mes(request)
    anio = _anio_de(mes)
    cargo = request.GET.get("cargo", "")
    estado = request.GET.get("estado", "activos")
    qs = Trabajador.objects.select_related("usuario").prefetch_related("horarios")
    if cargo in Trabajador.Cargo.values:
        qs = qs.filter(cargo=cargo)
    if estado == "activos":
        qs = qs.filter(activo=True)
    elif estado == "inactivos":
        qs = qs.filter(activo=False)
    trabajadores = list(qs)
    total = Decimal("0")
    for t in trabajadores:
        t.sem = calculo.semana(t, anio)
        t.mes = calculo.mes(t, anio, mes)
        if t.activo:
            total += t.mes["pago"]
    from django.contrib.auth import get_user_model

    sin_ficha = get_user_model().objects.filter(trabajador__isnull=True, is_active=True, asignaciones__isnull=False).distinct()
    return render(request, "personal/lista.html", {
        "trabajadores": trabajadores, "mes": mes, "nombre_mes": MESES[mes.month], "anio": anio,
        "cargos": Trabajador.Cargo.choices, "cargo": cargo, "estado": estado, "total": total,
        "sin_ficha": sin_ficha,
    })


# --- Ficha ------------------------------------------------------------------

def _guardar_horario(request, t):
    """Lee los campos h_<dia>_<n>_i / _f (dos turnos por día) y reemplaza el horario."""
    nuevos, errores = [], []
    for d, nombre in DIAS_LABORALES:
        for n in (1, 2):
            i, f = request.POST.get(f"h_{d}_{n}_i", ""), request.POST.get(f"h_{d}_{n}_f", "")
            if not i and not f:
                continue
            try:
                ti, tf = time.fromisoformat(i), time.fromisoformat(f)
            except ValueError:
                errores.append(f"{nombre}: completa la hora de entrada y de salida.")
                continue
            if tf <= ti:
                errores.append(f"{nombre}: la salida debe ser después de la entrada.")
                continue
            nuevos.append(HorarioTrabajador(trabajador=t, dia=d, inicio=ti, fin=tf))
    return nuevos, errores


def _filas_horario(t, post=None):
    filas = []
    actuales = {}
    for h in t.horarios.all() if t and t.pk else []:
        actuales.setdefault(h.dia, []).append(h)
    for d, nombre in DIAS_LABORALES:
        turnos = []
        for n in (1, 2):
            if post is not None:
                turnos.append((n, post.get(f"h_{d}_{n}_i", ""), post.get(f"h_{d}_{n}_f", "")))
            else:
                lista = actuales.get(d, [])
                h = lista[n - 1] if len(lista) >= n else None
                turnos.append((n, h.inicio.strftime("%H:%M") if h else "", h.fin.strftime("%H:%M") if h else ""))
        filas.append({"dia": d, "nombre": nombre, "turnos": turnos})
    return filas


@permiso_requerido("personal.editar")
def formulario(request, pk=None):
    t = get_object_or_404(Trabajador, pk=pk) if pk else None
    inicial = {}
    if t is None and request.GET.get("cargo") in Trabajador.Cargo.values:
        inicial["cargo"] = request.GET["cargo"]
        inicial["dar_acceso"] = request.GET["cargo"] == Trabajador.Cargo.DOCENTE
    form = TrabajadorForm(request.POST or None, instance=t, initial=inicial)
    errores_horario = []
    if request.method == "POST":
        nuevos, errores_horario = _guardar_horario(request, t or Trabajador())
        if form.is_valid() and not errores_horario:
            with transaction.atomic():
                t = form.save()
                t.horarios.all().delete()
                for h in nuevos:
                    h.trabajador = t
                HorarioTrabajador.objects.bulk_create(nuevos)
            msg = f"Datos de {t.nombres} {t.apellidos} guardados."
            if form.clave:
                msg += f" Se creó su acceso: usuario «{t.usuario.username}», contraseña inicial «{form.clave}». Anótala y entrégasela; podrá cambiarla al ingresar."
            messages.success(request, msg)
            return redirect("personal:detalle", pk=t.pk)
        for e in errores_horario:
            messages.error(request, e)
    return render(request, "personal/form.html", {
        "form": form, "t": t, "filas": _filas_horario(t, request.POST if request.method == "POST" else None),
    })


@permiso_requerido("personal.ver")
def detalle(request, pk):
    t = get_object_or_404(Trabajador.objects.select_related("usuario"), pk=pk)
    mes = _mes(request)
    anio = _anio_de(mes)
    sem = calculo.semana(t, anio)
    m = calculo.mes(t, anio, mes)
    clases = horario_de_docente(t.usuario, anio) if t.usuario_id and anio else None
    asignaciones = t.usuario.asignaciones.filter(seccion__anio_lectivo=anio).select_related("curso", "seccion__grado") if t.usuario_id and anio else []
    tutorias = t.usuario.tutorias.filter(anio_lectivo=anio).select_related("grado__nivel") if t.usuario_id and anio else []
    anterior = (mes.replace(day=1) - timezone.timedelta(days=1)).replace(day=1)
    siguiente = calculo.rango_mes(mes)[1] + timezone.timedelta(days=1)
    return render(request, "personal/detalle.html", {
        "t": t, "sem": sem, "m": m, "mes": mes, "nombre_mes": MESES[mes.month], "anio": anio,
        "clases": clases, "dias": DIAS_SEMANA, "horarios": t.horarios.all(),
        "asignaciones": asignaciones, "tutorias": tutorias, "anterior": anterior, "siguiente": siguiente,
    })


# --- Planilla estimada del mes -----------------------------------------------

@permiso_requerido("personal.planilla")
def planilla(request):
    mes = _mes(request)
    anio = _anio_de(mes)
    filas = []
    for t in Trabajador.objects.filter(activo=True).prefetch_related("horarios").select_related("usuario"):
        filas.append((t, calculo.mes(t, anio, mes)))
    total = sum((m["pago"] for _, m in filas), Decimal("0"))
    if request.GET.get("excel"):
        return _planilla_excel(filas, mes, total)
    anterior = (mes - timezone.timedelta(days=1)).replace(day=1)
    siguiente = calculo.rango_mes(mes)[1] + timezone.timedelta(days=1)
    return render(request, "personal/planilla.html", {
        "filas": filas, "mes": mes, "nombre_mes": MESES[mes.month], "total": total, "anio": anio,
        "dias_lectivos": filas[0][1]["dias_lectivos"] if filas else 0,
        "anterior": anterior, "siguiente": siguiente,
    })


def _planilla_excel(filas, mes, total):
    wb = Workbook()
    ws = wb.active
    ws.title = f"Planilla {mes:%m-%Y}"
    ws["A1"] = f"Planilla estimada – {MESES[mes.month]} {mes.year}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = "Estimación: no incluye descuentos ni aportes de ley (ONP/AFP, EsSalud, renta), gratificaciones ni CTS."
    enc = ["Trabajador", "DNI", "Cargo", "Modalidad", "Horas de clase", "Horas de horario", "Otras horas",
           "Horas totales", "Tarifa / sueldo", "Pago estimado (S/)", "Cuenta"]
    ws.append([])
    ws.append(enc)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0D6EFD")
    for t, m in filas:
        ws.append([
            str(t), t.numero_documento, t.get_cargo_display(), t.get_modalidad_display(),
            m["clases"], float(m["horario_propio"]), float(m["extra"]), float(m["horas"]),
            float(t.sueldo if t.modalidad == Trabajador.Modalidad.MENSUAL else t.pago_hora),
            float(m["pago"]), t.cuenta_bancaria,
        ])
    ws.append([])
    ws.append(["TOTAL"] + [""] * 8 + [float(total)])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.cell(row=ws.max_row, column=10).font = Font(bold=True)
    for i, w in enumerate([32, 11, 22, 18, 12, 14, 11, 12, 14, 16, 24], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for fila in ws.iter_rows(min_row=5, min_col=9, max_col=10):
        for c in fila:
            c.number_format = "#,##0.00"
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"planilla_estimada_{mes:%Y_%m}.xlsx")
    return resp


@permiso_requerido("personal.editar")
def importar_usuarios(request):
    """Crea fichas de personal para los usuarios (docentes) que aún no tienen."""
    from django.contrib.auth import get_user_model

    if request.method != "POST":
        return redirect("personal:lista")
    creados = 0
    for u in get_user_model().objects.filter(trabajador__isnull=True, is_active=True, asignaciones__isnull=False).distinct():
        Trabajador.objects.create(
            usuario=u, numero_documento=f"PEND-{u.pk}", apellidos=u.last_name or u.username, nombres=u.first_name or u.username,
            cargo=Trabajador.Cargo.DOCENTE, email=u.email, modalidad=Trabajador.Modalidad.POR_HORA,
        )
        creados += 1
    messages.success(request, f"Se crearon {creados} fichas. Completa su DNI y pago en cada una.")
    return redirect(reverse("personal:lista"))
