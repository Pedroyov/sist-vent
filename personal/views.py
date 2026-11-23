from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.permisos import modulos_activos, permiso_requerido

from .forms import PersonaForm
from .models import Persona


def _comisiones():
    from core.models import Ajustes

    return Ajustes.cargar().usa_comisiones


def _pagos():
    from core.models import Ajustes

    return Ajustes.cargar().usa_pagos


@permiso_requerido("personal.editar")
def lista(request):
    modulos = modulos_activos()
    hoy = timezone.localdate()
    personas = list(Persona.objects.select_related("usuario").prefetch_related("servicios"))
    con_citas = "citas" in modulos
    for p in personas:
        if con_citas:
            p.dias = [h.get_dia_display()[:3] for h in p.horarios.all()]
            p.proxima_ausencia = p.ausencias.filter(hasta__gte=hoy).first()
    ctx = {"lista": personas, "con_citas": con_citas, "con_delivery": "delivery" in modulos, "comisiones": _comisiones(), "pagos": _pagos()}
    if con_citas:
        from citas.forms import ConfigForm
        from citas.models import Config

        ctx["form_cfg"] = ConfigForm(instance=Config.cargar())
    return render(request, "personal/lista.html", ctx)


@permiso_requerido("personal.editar")
def ficha(request, pk=None):
    p = get_object_or_404(Persona, pk=pk) if pk else None
    modulos = modulos_activos()
    con_citas = "citas" in modulos
    kw = {"modulos": modulos, "comisiones": _comisiones(), "pagos": _pagos()}
    dias = None
    if con_citas:
        from citas.forms import HorariosFormSet
        from citas.views import guardar_horarios, horarios_de
    if request.method == "POST":
        form = PersonaForm(request.POST, instance=p, **kw)
        if con_citas:
            dias = HorariosFormSet(request.POST, prefix="h")
        if form.is_valid() and (dias is None or dias.is_valid()):
            with transaction.atomic():
                p = form.save()
                if dias is not None and p.atiende_citas:
                    guardar_horarios(p, dias)
                if p.usuario_id:
                    _dar_rol(p.usuario)
            messages.success(request, f"{p.nombre} guardado.")
            return redirect("personal:persona", pk=p.pk)
    else:
        form = PersonaForm(instance=p, **kw)
        if con_citas:
            dias = HorariosFormSet(initial=horarios_de(p), prefix="h")
    ctx = {"form": form, "p": p, "con_citas": con_citas, "hoy": timezone.localdate()}
    if con_citas:
        from citas.forms import AusenciaForm
        from citas.models import DIAS

        hoy = timezone.localdate()
        ctx.update({"dias": dias, "filas": list(zip(DIAS, dias.forms)), "form_aus": AusenciaForm(initial={"desde": hoy, "hasta": hoy}),
                    "ausencias": p.ausencias.filter(hasta__gte=hoy - timedelta(days=30)).order_by("-desde") if p else []})
    return render(request, "personal/ficha.html", ctx)


@permiso_requerido("personal.editar")
def pagos(request):
    """Cuánto le toca a cada persona en el periodo, cuánto ya se le pagó y cuánto falta (función «Pagos al personal»)."""
    from caja.models import SesionCaja
    from core.permisos import puede
    from reportes.servicios import ATAJOS, periodo

    from .pagos import cuentas

    if not _pagos():
        messages.info(request, "Activa «Pagos al personal» en Configuración → Módulos del sistema.")
        return redirect("personal:lista")
    desde, hasta, atajo = periodo(request, defecto="mes")
    c = cuentas(desde, hasta)
    if request.GET.get("excel"):
        from core.excel import descargar

        return descargar("pagos_personal", [(f"{desde:%d.%m} al {hasta:%d.%m.%Y}", ["Persona", "Sueldo", "Comisión", "Le toca", "Pagado", "Falta"],
                                             [[f["persona"].nombre, f["sueldo"], f["comision"], f["toca"], f["pagado"], f["falta"]]
                                              for f in c["filas"]])])
    caja = SesionCaja.abierta_de(request.user) if puede(request.user, "caja.usar") else None
    return render(request, "personal/pagos.html", {
        "desde": desde, "hasta": hasta, "atajo": atajo, "atajos": ATAJOS, "c": c, "caja": caja,
        "fuera": puede(request.user, "caja.ver"), "volver": request.get_full_path(),
    })


def _dar_rol(user):
    """Quien atiende citas y tiene usuario sin rol recibe «Profesional» (ve su agenda)."""
    from django.contrib.auth.models import Group

    from core.permisos import PROFESIONAL

    if not user.groups.exists() and not user.is_superuser and getattr(getattr(user, "persona", None), "atiende_citas", False) \
            and "citas" in modulos_activos():
        g = Group.objects.filter(name=PROFESIONAL).first()
        if g:
            user.groups.add(g)
