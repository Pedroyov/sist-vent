from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from alumnos.models import Alumno, Matricula
from core.colegio import nombre as colegio_nombre
from core.models import AnioLectivo
from core.permisos import permiso_requerido, puede

from . import servicios
from .forms import AnularPagoForm, ConfigCobranzaForm, DescuentoForm, PagoForm
from .models import CERO, Cargo, ConfigCobranza, Concepto, Descuento, Pago, dinero



def _anio_o_aviso(request):
    anio = AnioLectivo.actual()
    if anio is None:
        messages.warning(request, "Primero crea el año lectivo en Configuración.")
    return anio


def _decimal(texto):
    try:
        valor = Decimal((texto or "0").replace(",", ".").strip() or "0")
        if not valor.is_finite() or abs(valor) > 10_000_000:
            return None
        return dinero(valor)
    except InvalidOperation:
        return None


# --- Inicio: buscar alumno y resumen del día --------------------------------

@permiso_requerido("cobranza.ver")
def inicio(request):
    anio = _anio_o_aviso(request)
    if anio is None:
        return redirect("core:inicio")
    config = ConfigCobranza.objects.filter(anio_lectivo=anio).first()
    q = request.GET.get("q", "").strip()
    resultados = []
    if q:
        alumnos = Alumno.objects.filter(matriculas__anio_lectivo=anio)
        for palabra in q.split():
            alumnos = alumnos.filter(
                Q(numero_documento__icontains=palabra) | Q(apellido_paterno__icontains=palabra)
                | Q(apellido_materno__icontains=palabra) | Q(nombres__icontains=palabra)
                | Q(vinculos__apoderado__numero_documento__icontains=palabra)
                | Q(vinculos__apoderado__apellidos__icontains=palabra)
            )
        alumnos = alumnos.distinct()[:15]
        hoy = timezone.localdate()
        for a in alumnos:
            mat = a.matricula_en(anio)
            deuda = Cargo.objects.filter(alumno=a, concepto__anio_lectivo=anio).pendientes()
            a.mat = mat
            a.n_vencidos = deuda.filter(vencimiento__lt=hoy).count()
            a.saldo = sum((c.saldo for c in deuda), CERO)
            resultados.append(a)
    if request.htmx:
        return render(request, "cobranza/partials/resultados.html", {"resultados": resultados, "q": q})

    hoy = timezone.localdate()
    pagos_hoy = Pago.objects.filter(fecha=hoy, anulado=False)
    contexto = {
        "anio": anio, "config": config, "q": q, "resultados": resultados,
        "cobrado_hoy": dinero(pagos_hoy.aggregate(t=Sum("total"))["t"] or CERO),
        "n_pagos_hoy": pagos_hoy.count(),
        "cobrado_mes": servicios.cobrado_en(hoy.replace(day=1), hoy),
        "ultimos": Pago.objects.select_related("alumno").filter(anio_lectivo=anio)[:8],
        "vencido": dinero(sum((c.saldo for c in Cargo.objects.vencidos(hoy).filter(concepto__anio_lectivo=anio)), CERO)),
    }
    return render(request, "cobranza/inicio.html", contexto)


# --- Configuración y cronograma ---------------------------------------------

@permiso_requerido("cobranza.configurar")
def configuracion(request):
    anio = _anio_o_aviso(request)
    if anio is None:
        return redirect("core:anio_nuevo")
    config = ConfigCobranza.objects.filter(anio_lectivo=anio).first()
    inicial = {}
    if config is None:
        inicial = {"mes_inicio": max(anio.fecha_inicio.month, 1), "mes_fin": anio.fecha_fin.month}
    form = ConfigCobranzaForm(request.POST or None, instance=config, initial=inicial)
    if request.method == "POST" and form.is_valid():
        config = form.save(commit=False)
        config.anio_lectivo = anio
        config.save()
        avisos = servicios.generar_conceptos(config)
        nuevos = servicios.sincronizar_anio(anio)
        messages.success(request, f"Cronograma de {anio} guardado. Se generaron {nuevos} deudas nuevas para los alumnos matriculados.")
        for a in avisos:
            messages.warning(request, a)
        return redirect("cobranza:configuracion")
    conceptos = Concepto.objects.filter(anio_lectivo=anio).annotate(
        n_cargos=Count("cargos", filter=Q(cargos__anulado=False))
    )
    total_anual = sum((c.monto for c in conceptos if c.automatico), CERO)
    return render(request, "cobranza/configuracion.html", {
        "form": form, "anio": anio, "config": config, "conceptos": conceptos, "total_anual": total_anual,
        "matriculados": Matricula.objects.filter(anio_lectivo=anio, estado=Matricula.Estado.MATRICULADO).count(),
    })


# --- Estado de cuenta y cobro -----------------------------------------------

@permiso_requerido("cobranza.ver", "cobranza.cobrar")
def cobrar(request, alumno_pk):
    alumno = get_object_or_404(Alumno, pk=alumno_pk)
    anio = _anio_o_aviso(request)
    if anio is None:
        return redirect("core:inicio")
    resumen = servicios.resumen_alumno(alumno, anio)
    pendientes = [c for c in resumen["cargos"] if not c.anulado and c.saldo > 0]
    form = PagoForm(request.POST or None, request.FILES or None)
    seleccion = {}

    if request.method == "POST":
        if not puede(request.user, "cobranza.cobrar"):
            raise PermissionDenied
        items, error = [], None
        for c in pendientes:
            if request.POST.get(f"sel_{c.pk}") != "on":
                continue
            monto = _decimal(request.POST.get(f"monto_{c.pk}"))
            mora = _decimal(request.POST.get(f"mora_{c.pk}"))
            if monto is None or mora is None:
                error = f"Monto no válido en «{c.concepto}»."
                break
            seleccion[c.pk] = (monto, mora)
            items.append((c.pk, monto, mora))
        if error:
            messages.error(request, error)
        elif form.is_valid():
            try:
                pago = servicios.registrar_pago(
                    alumno=alumno, anio=anio, items=items, usuario=request.user,
                    fecha=form.cleaned_data["fecha"], metodo=form.cleaned_data["metodo"],
                    numero_operacion=form.cleaned_data["numero_operacion"],
                    voucher=form.cleaned_data.get("voucher"), observacion=form.cleaned_data["observacion"],
                )
            except servicios.ErrorPago as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f"Pago registrado: recibo N° {pago.numero_texto} por S/ {pago.total}.")
                return redirect("cobranza:recibo", pk=pago.pk)

    if request.method != "POST" and pendientes:
        # al abrir: marcar las vencidas (?sel=vencidas) o, por defecto, la cuota más antigua
        if request.GET.get("sel") == "vencidas":
            seleccion = {c.pk: (c.saldo, c.mora_hoy) for c in pendientes if c.vencido}
        if not seleccion:
            primera = pendientes[0]
            seleccion = {primera.pk: (primera.saldo, primera.mora_hoy)}
    for c in pendientes:
        c.sel = c.pk in seleccion
        c.monto_form, c.mora_form = seleccion.get(c.pk, (c.saldo, c.mora_hoy))

    contexto = {
        "alumno": alumno, "anio": anio, "mat": alumno.matricula_en(anio), "r": resumen,
        "pendientes": pendientes,
        "cancelados": [c for c in resumen["cargos"] if c.anulado or c.saldo == 0],
        "pagos": alumno.pagos.filter(anio_lectivo=anio).prefetch_related("detalles__cargo__concepto"),
        "descuentos": alumno.descuentos.filter(anio_lectivo=anio),
        "form": form, "form_desc": DescuentoForm(),
        "apoderado": alumno.apoderado_principal,
        "hoy": timezone.localdate(),
    }
    return render(request, "cobranza/cobrar.html", contexto)


@permiso_requerido("cobranza.ver")
def recibo(request, pk):
    pago = get_object_or_404(
        Pago.objects.select_related("alumno", "anio_lectivo", "registrado_por", "anulado_por"), pk=pk
    )
    detalles = pago.detalles.select_related("cargo__concepto")
    apoderado = pago.alumno.apoderado_principal
    mat = pago.alumno.matricula_en(pago.anio_lectivo)
    lineas = "\n".join(f"• {d.cargo.concepto}: S/ {d.subtotal}" for d in detalles)
    texto = (
        f"*{colegio_nombre()}*\n"
        f"Recibo N° {pago.numero_texto} – {pago.fecha:%d/%m/%Y}\n"
        f"Alumno(a): {pago.alumno.nombres} {pago.alumno.apellidos}\n"
        f"{lineas}\n"
        f"*Total pagado: S/ {pago.total}* ({pago.get_metodo_display()})\n"
        f"¡Gracias por su pago!"
    )
    wa = f"https://wa.me/{apoderado.whatsapp}?text={quote(texto)}" if apoderado and apoderado.whatsapp else None
    return render(request, "cobranza/recibo.html", {
        "pago": pago, "detalles": detalles, "apoderado": apoderado, "mat": mat, "wa": wa,
        "puede_anular": puede(request.user, "cobranza.anular"), "form_anular": AnularPagoForm(),
    })


@permiso_requerido("cobranza.anular")
@require_POST
def anular(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    form = AnularPagoForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indica el motivo de la anulación.")
    else:
        try:
            servicios.anular_pago(pago, request.user, form.cleaned_data["motivo"])
            messages.success(request, f"Recibo {pago.numero_texto} anulado. La deuda volvió a quedar pendiente.")
        except servicios.ErrorPago as e:
            messages.error(request, str(e))
    return redirect("cobranza:recibo", pk=pago.pk)


# --- Descuentos -------------------------------------------------------------

@permiso_requerido("cobranza.descuentos")
@require_POST
def descuento_agregar(request, alumno_pk):
    alumno = get_object_or_404(Alumno, pk=alumno_pk)
    anio = AnioLectivo.actual()
    form = DescuentoForm(request.POST)
    if form.is_valid():
        d = form.save(commit=False)
        d.alumno, d.anio_lectivo = alumno, anio
        d.save()
        messages.success(request, f"Descuento «{d}» agregado. Se recalcularon las deudas pendientes.")
    else:
        errores = "; ".join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f"No se pudo agregar el descuento: {errores}")
    return redirect(reverse("cobranza:cobrar", args=[alumno.pk]) + "#descuentos")


@permiso_requerido("cobranza.descuentos")
@require_POST
def descuento_eliminar(request, pk):
    d = get_object_or_404(Descuento, pk=pk)
    alumno_pk = d.alumno_id
    d.delete()
    messages.success(request, "Descuento eliminado. Se recalcularon las deudas pendientes.")
    return redirect(reverse("cobranza:cobrar", args=[alumno_pk]) + "#descuentos")


# --- Pagos del día (caja) ---------------------------------------------------

@permiso_requerido("cobranza.ver")
def pagos(request):
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
    lista = (
        Pago.objects.filter(fecha__range=(desde, hasta))
        .select_related("alumno", "registrado_por")
        .order_by("-fecha", "-numero")
    )
    validos = lista.filter(anulado=False)
    por_metodo = OrderedDict()
    for fila in validos.values("metodo").annotate(t=Sum("total"), n=Count("id")).order_by("-t"):
        por_metodo[Pago.Metodo(fila["metodo"]).label] = (dinero(fila["t"]), fila["n"])
    return render(request, "cobranza/pagos.html", {
        "pagos": lista, "desde": desde, "hasta": hasta,
        "total": dinero(validos.aggregate(t=Sum("total"))["t"] or CERO), "n": validos.count(),
        "por_metodo": por_metodo,
        "ayer": hoy - timedelta(days=1), "hoy": hoy, "inicio_mes": hoy.replace(day=1),
    })
