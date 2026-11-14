"""
Cobro rápido: se elige primero QUÉ se cobra (p. ej. "Pensión Abril") y luego
se registra el pago de cada alumno con un toque, o de varios a la vez.
"""
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from alumnos.models import AlumnoApoderado, Matricula
from alumnos.utils import filtro_en, opciones_en
from core.models import AnioLectivo
from core.permisos import permiso_requerido

from . import servicios
from .models import CERO, Cargo, ConfigCobranza, Concepto, Pago
from .views import _decimal



def _concepto_por_defecto(conceptos, hoy):
    """La pensión del mes actual; si no hay, la próxima en vencer; si no, la última."""
    for c in conceptos:
        if c.tipo == Concepto.Tipo.PENSION and c.vencimiento.year == hoy.year and c.vencimiento.month == hoy.month:
            return c
    futuros = [c for c in conceptos if c.vencimiento >= hoy]
    if futuros:
        return min(futuros, key=lambda c: c.vencimiento)
    return conceptos[-1] if conceptos else None


def _filas(concepto, en=""):
    cargos = (
        Cargo.objects.pendientes().filter(concepto=concepto)
        .select_related("alumno")
        .order_by("alumno__apellido_paterno", "alumno__apellido_materno", "alumno__nombres")
    )
    mats = Matricula.objects.filter(anio_lectivo=concepto.anio_lectivo).select_related("seccion__grado__nivel")
    if en:
        mats = mats.filter(filtro_en(en))
        cargos = cargos.filter(alumno_id__in=mats.values("alumno_id"))
    cargos = list(cargos)
    mat_de = {m.alumno_id: m for m in mats.filter(alumno_id__in=[c.alumno_id for c in cargos])}
    apo_de = {}
    for v in AlumnoApoderado.objects.filter(alumno_id__in=[c.alumno_id for c in cargos]).select_related("apoderado").order_by("-responsable_pago", "id"):
        apo_de.setdefault(v.alumno_id, v.apoderado)
    config = ConfigCobranza.objects.filter(anio_lectivo=concepto.anio_lectivo).first()
    hoy = timezone.localdate()
    for c in cargos:
        c.mat = mat_de.get(c.alumno_id)
        c.apo = apo_de.get(c.alumno_id)
        c.mora_hoy = c.mora(config, hoy)
    return cargos, config


@permiso_requerido("cobranza.cobrar")
def rapido(request):
    anio = AnioLectivo.actual()
    if anio is None:
        return redirect("core:inicio")
    hoy = timezone.localdate()
    conceptos = list(Concepto.objects.filter(anio_lectivo=anio).order_by("vencimiento", "tipo", "nombre"))
    pk = request.GET.get("concepto", "")
    concepto = next((c for c in conceptos if str(c.pk) == pk), None) or _concepto_por_defecto(conceptos, hoy)
    en = request.GET.get("en", "")
    filas, config = _filas(concepto, en) if concepto else ([], None)
    pagados_hoy = (
        Pago.objects.filter(anulado=False, fecha=hoy, detalles__cargo__concepto=concepto).distinct().count()
        if concepto else 0
    )
    return render(request, "cobranza/rapido.html", {
        "anio": anio, "conceptos": conceptos, "concepto": concepto, "filas": filas, "config": config,
        "opciones_en": opciones_en(anio), "en": en, "metodos": Pago.Metodo.choices,
        "pendiente": sum((f.saldo for f in filas), CERO), "pagados_hoy": pagados_hoy,
    })


@permiso_requerido("cobranza.cobrar")
def rapido_form(request, cargo_pk):
    """HTMX: muestra el mini formulario de pago dentro de la fila."""
    cargo = get_object_or_404(Cargo.objects.select_related("alumno", "concepto"), pk=cargo_pk)
    config = ConfigCobranza.objects.filter(anio_lectivo=cargo.concepto.anio_lectivo).first()
    cargo.mora_hoy = cargo.mora(config)
    if request.GET.get("cancelar"):
        filas, _ = _filas(cargo.concepto)
        fila = next((f for f in filas if f.pk == cargo.pk), cargo)
        return render(request, "cobranza/partials/rapido_fila.html", {"c": fila, "config": config})
    return render(request, "cobranza/partials/rapido_pagar.html", {
        "c": cargo, "config": config, "metodos": Pago.Metodo.choices,
    })


@permiso_requerido("cobranza.cobrar")
@require_POST
def rapido_pagar(request, cargo_pk):
    """HTMX: registra el pago de una fila y la reemplaza por "Pagado"."""
    cargo = get_object_or_404(Cargo.objects.select_related("alumno", "concepto__anio_lectivo"), pk=cargo_pk)
    config = ConfigCobranza.objects.filter(anio_lectivo=cargo.concepto.anio_lectivo).first()
    cargo.mora_hoy = cargo.mora(config)
    monto = _decimal(request.POST.get("monto"))
    mora = _decimal(request.POST.get("mora")) if config and config.mora_activa else CERO
    metodo = request.POST.get("metodo", Pago.Metodo.EFECTIVO)
    operacion = request.POST.get("numero_operacion", "").strip()
    error = None
    if monto is None or mora is None:
        error = "Monto no válido."
    elif metodo not in Pago.Metodo.values:
        error = "Elige el método de pago."
    elif metodo != Pago.Metodo.EFECTIVO and not operacion:
        error = "Anota el N° de operación."
    if not error:
        try:
            pago = servicios.registrar_pago(
                alumno=cargo.alumno, anio=cargo.concepto.anio_lectivo, items=[(cargo.pk, monto, mora)],
                usuario=request.user, metodo=metodo, numero_operacion=operacion,
            )
        except servicios.ErrorPago as e:
            error = str(e)
    if error:
        return render(request, "cobranza/partials/rapido_pagar.html", {
            "c": cargo, "config": config, "metodos": Pago.Metodo.choices, "error": error,
            "monto": request.POST.get("monto"), "mora": request.POST.get("mora"), "metodo": metodo, "operacion": operacion,
        })
    cargo.refresh_from_db()
    return render(request, "cobranza/partials/rapido_pagado.html", {"c": cargo, "pago": pago})


@permiso_requerido("cobranza.cobrar")
@require_POST
def rapido_lote(request, concepto_pk):
    """Registra de una vez el pago completo de los alumnos marcados (un recibo por alumno)."""
    concepto = get_object_or_404(Concepto, pk=concepto_pk)
    metodo = request.POST.get("metodo_lote", Pago.Metodo.EFECTIVO)
    if metodo not in Pago.Metodo.values:
        metodo = Pago.Metodo.EFECTIVO
    ids = [i for i in request.POST.getlist("cargos") if i.isdigit()]
    config = ConfigCobranza.objects.filter(anio_lectivo=concepto.anio_lectivo).first()
    cargos = Cargo.objects.pendientes().filter(pk__in=ids, concepto=concepto).select_related("alumno")
    hechos, total = 0, CERO
    with transaction.atomic():
        for c in cargos:
            mora = c.mora(config)
            pago = servicios.registrar_pago(
                alumno=c.alumno, anio=concepto.anio_lectivo, items=[(c.pk, c.saldo, mora)],
                usuario=request.user, metodo=metodo, observacion="Cobro rápido",
            )
            hechos += 1
            total += pago.total
    if hechos:
        messages.success(request, f"Se registraron {hechos} pago{'s' if hechos != 1 else ''} de «{concepto}» por S/ {total}.")
    else:
        messages.warning(request, "No marcaste ningún alumno (o ya estaban pagados).")
    url = reverse("cobranza:rapido") + f"?concepto={concepto.pk}"
    if request.POST.get("en"):
        url += f"&en={request.POST['en']}"
    return redirect(url)
