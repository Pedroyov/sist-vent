"""Otros cobros: conceptos que se asignan a todo el colegio, a un grado/sección o a alumnos puntuales."""
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from alumnos.models import Matricula
from alumnos.utils import filtro_en, opciones_en
from core.forms import FECHA
from core.models import AnioLectivo
from core.permisos import permiso_requerido

from .models import CERO, Cargo, Concepto, dinero



class OtroCobroForm(forms.ModelForm):
    class Meta:
        model = Concepto
        fields = ["nombre", "monto", "vencimiento"]
        labels = {"nombre": "Concepto", "vencimiento": "Fecha de vencimiento"}
        help_texts = {"nombre": 'Ej.: "APAFA", "Materiales", "Paseo de promoción"'}
        widgets = {
            "vencimiento": FECHA,
            "monto": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        }

    def clean_monto(self):
        monto = self.cleaned_data["monto"]
        if monto <= 0:
            raise forms.ValidationError("El monto debe ser mayor que cero.")
        return monto


def _matriculas(anio):
    return (
        Matricula.objects.filter(anio_lectivo=anio, estado=Matricula.Estado.MATRICULADO)
        .select_related("alumno", "seccion__grado__nivel")
        .order_by("seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre",
                  "alumno__apellido_paterno", "alumno__apellido_materno", "alumno__nombres")
    )


def _destinatarios(request, anio):
    """Alumnos elegidos en el formulario (todos, por grado/sección o marcados uno por uno)."""
    modo = request.POST.get("modo", "todos")
    mats = _matriculas(anio)
    if modo == "grupo":
        en = request.POST.get("en", "")
        if not en:
            return None, "Elige el nivel, grado o sección."
        mats = mats.filter(filtro_en(en))
    elif modo == "alumnos":
        ids = [i for i in request.POST.getlist("alumnos") if i.isdigit()]
        if not ids:
            return None, "Marca al menos un alumno."
        mats = mats.filter(alumno_id__in=ids)
    return [m.alumno for m in mats], None


def _asignar(concepto, alumnos):
    existentes = set(concepto.cargos.values_list("alumno_id", flat=True))
    nuevos = [
        Cargo(alumno=a, concepto=concepto, monto=concepto.monto, vencimiento=concepto.vencimiento)
        for a in alumnos if a.pk not in existentes
    ]
    Cargo.objects.bulk_create(nuevos)
    reactivados = concepto.cargos.filter(alumno__in=alumnos, anulado=True, pagado=0).update(anulado=False)
    return len(nuevos) + reactivados


@permiso_requerido("cobranza.ver", "cobranza.otros")
def lista(request):
    anio = AnioLectivo.actual()
    if anio is None:
        return redirect("core:inicio")
    conceptos = (
        Concepto.objects.filter(anio_lectivo=anio, tipo=Concepto.Tipo.OTRO)
        .annotate(
            n=Count("cargos", filter=Q(cargos__anulado=False)),
            cobrado=Sum("cargos__pagado", filter=Q(cargos__anulado=False)),
        )
        .order_by("-vencimiento", "nombre")
    )
    for c in conceptos:
        c.cobrado = dinero(c.cobrado or CERO)
        c.esperado = dinero(c.monto * c.n)
    return render(request, "cobranza/otros_lista.html", {"anio": anio, "conceptos": conceptos})


def _form_destino_contexto(anio):
    return {"opciones_en": opciones_en(anio), "matriculas": _matriculas(anio)}


@permiso_requerido("cobranza.otros")
def nuevo(request):
    anio = AnioLectivo.actual()
    if anio is None:
        return redirect("core:inicio")
    form = OtroCobroForm(request.POST or None, initial={"vencimiento": anio.fecha_inicio})
    if request.method == "POST" and form.is_valid():
        alumnos, error = _destinatarios(request, anio)
        if error:
            messages.error(request, error)
        elif not alumnos:
            messages.error(request, "No hay alumnos matriculados que cumplan esa condición.")
        else:
            with transaction.atomic():
                c = form.save(commit=False)
                c.anio_lectivo, c.tipo, c.automatico = anio, Concepto.Tipo.OTRO, False
                c.save()
                n = _asignar(c, alumnos)
            messages.success(request, f"Cobro «{c.nombre}» creado y asignado a {n} alumno{'s' if n != 1 else ''}.")
            return redirect("cobranza:otro_detalle", pk=c.pk)
    contexto = {"form": form, "anio": anio, "modo": request.POST.get("modo", "todos"),
                "en": request.POST.get("en", ""), "marcados": set(request.POST.getlist("alumnos")),
                "ya_asignados": set()}
    contexto.update(_form_destino_contexto(anio))
    return render(request, "cobranza/otro_form.html", contexto)


@permiso_requerido("cobranza.ver", "cobranza.otros")
def detalle(request, pk):
    c = get_object_or_404(Concepto, pk=pk, tipo=Concepto.Tipo.OTRO)
    form = OtroCobroForm(request.POST or None, instance=c)

    if request.method == "POST" and request.POST.get("accion") == "editar":
        if form.is_valid():
            with transaction.atomic():
                form.save()
                c.cargos.filter(pagado=0).update(monto=c.monto, vencimiento=c.vencimiento)
            messages.success(request, "Cobro actualizado. Se cambió en las deudas que aún no tienen pagos.")
            return redirect("cobranza:otro_detalle", pk=c.pk)
    elif request.method == "POST" and request.POST.get("accion") == "agregar":
        alumnos, error = _destinatarios(request, c.anio_lectivo)
        if error:
            messages.error(request, error)
        else:
            n = _asignar(c, alumnos or [])
            messages.success(request, f"Se agregó el cobro a {n} alumno{'s' if n != 1 else ''} más.")
            return redirect("cobranza:otro_detalle", pk=c.pk)

    cargos = list(
        c.cargos.select_related("alumno").order_by("anulado", "alumno__apellido_paterno", "alumno__nombres")
    )
    vigentes = [x for x in cargos if not x.anulado]
    contexto = {
        "c": c, "form": form, "cargos": cargos,
        "n": len(vigentes), "pagados": sum(1 for x in vigentes if x.cancelado),
        "cobrado": sum((x.pagado for x in vigentes), CERO),
        "pendiente": sum((x.saldo for x in vigentes), CERO),
        "modo": "alumnos", "marcados": set(), "en": "",
    }
    contexto.update(_form_destino_contexto(c.anio_lectivo))
    contexto["ya_asignados"] = {x.alumno_id for x in vigentes}
    return render(request, "cobranza/otro_detalle.html", contexto)


@permiso_requerido("cobranza.otros")
@require_POST
def quitar(request, cargo_pk):
    cargo = get_object_or_404(Cargo, pk=cargo_pk, concepto__tipo=Concepto.Tipo.OTRO)
    if cargo.pagado > 0:
        messages.error(request, "No se puede quitar: ya tiene pagos. Anula primero el recibo.")
    else:
        cargo.delete()
        messages.success(request, f"Se quitó el cobro a {cargo.alumno.nombre_completo}.")
    return redirect(reverse("cobranza:otro_detalle", args=[cargo.concepto_id]))


@permiso_requerido("cobranza.anular")
@require_POST
def eliminar(request, pk):
    c = get_object_or_404(Concepto, pk=pk, tipo=Concepto.Tipo.OTRO)
    if c.cargos.filter(pagado__gt=0).exists():
        messages.error(request, "No se puede eliminar: algunos alumnos ya pagaron este cobro.")
        return redirect("cobranza:otro_detalle", pk=c.pk)
    nombre = c.nombre
    with transaction.atomic():
        c.cargos.all().delete()
        c.delete()
    messages.success(request, f"Cobro «{nombre}» eliminado.")
    return redirect("cobranza:otros")
