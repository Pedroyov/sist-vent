import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permisos import modulo_activo, permiso_requerido, puede
from core.utils import entero, url_segura

from . import servicios as s
from .forms import CompraForm, PagoForm, ProveedorForm
from .models import CERO, Compra, Proveedor

BC = ("Compras", "compras:lista")


def _caja_abierta(user):
    """La caja abierta de quien paga, si puede pagar de su caja (módulo Caja activo y permiso caja.usar)."""
    from caja.models import SesionCaja

    if not (modulo_activo(user, "caja") and puede(user, "caja.usar")):
        return None
    return SesionCaja.abierta_de(user)


@permiso_requerido("compras.ver")
def lista(request):
    from reportes.servicios import ATAJOS, periodo

    desde, hasta, atajo = periodo(request, defecto="mes")
    qs = s.con_pagado(Compra.objects.filter(fecha__gte=desde, fecha__lte=hasta)).select_related("proveedor")
    proveedor = entero(request.GET.get("proveedor"))
    if proveedor:
        qs = qs.filter(proveedor_id=proveedor)
    estado = request.GET.get("estado", "")
    hoy = timezone.localdate()
    if estado == "anuladas":
        qs = qs.filter(anulada=True)
    else:
        qs = qs.filter(anulada=False)
        if estado == "pagadas":
            qs = qs.filter(total__lte=F("_pagado"))
        elif estado == "por_pagar":
            qs = qs.filter(total__gt=F("_pagado"))
        elif estado == "vencidas":
            qs = qs.filter(total__gt=F("_pagado"), vence__lt=hoy)
    vigentes = Compra.objects.filter(fecha__gte=desde, fecha__lte=hasta, anulada=False)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "compras/lista.html", {
        "pagina": Paginator(qs, 50).get_page(request.GET.get("page")), "query": query, "desde": desde, "hasta": hasta,
        "atajo": atajo, "atajos": ATAJOS, "estado": estado, "proveedor": proveedor,
        "proveedores": Proveedor.objects.filter(compras__isnull=False).distinct(),
        "comprado": vigentes.aggregate(t=Sum("total"))["t"] or CERO, "n": vigentes.count(),
        "deuda": sum((c.saldo for c in s.con_saldo()), CERO), "vencen": len(s.vencen_pronto()),
    })


def _catalogo():
    """Productos que se pueden comprar (controlan stock), para buscarlos en la pantalla."""
    from productos.models import Variante

    vs = (Variante.objects.filter(activa=True, producto__activo=True, producto__maneja_stock=True)
          .exclude(producto__tipo="C").select_related("producto").order_by("producto__nombre", "orden"))
    return [{"id": v.pk, "n": v.nombre_completo, "c": v.codigo or "", "k": str(v.costo_efectivo) if v.costo_efectivo is not None else "",
             "f": v.producto.fraccionable} for v in vs]


@permiso_requerido("compras.registrar")
def nueva(request):
    caja = _caja_abierta(request.user)
    hoy = timezone.localdate()
    inicial = {"fecha": hoy, "pago": "caja" if caja else "fuera", "proveedor": entero(request.GET.get("proveedor"))}
    form = CompraForm(request.POST or None, puede_caja=caja is not None, initial=inicial)
    error = ""
    previos = request.POST.get("items") or _reponer(request.GET.get("reponer"))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            items = json.loads(d["items"] or "[]")
            if not isinstance(items, list):
                raise ValueError
        except ValueError:
            items = None
        if items is None:
            error = "Las líneas no llegaron bien. Recarga la página."
        else:
            try:
                c = s.registrar_compra(request.user, d["proveedor"], items, d["documento"], d["serie"], d["numero"], d["fecha"],
                                       credito=d["pago"] == "credito", vence=d["vence"],
                                       pago=None if d["pago"] == "credito" else d["pago"], nota=d["nota"], token=d["token"] or None)
                messages.success(request, f"Compra registrada: {c.documento_str} por S/ {c.total:.2f}.")
                return redirect("compras:detalle", pk=c.pk)
            except s.CompraError as e:
                error = str(e)
    return render(request, "compras/nueva.html", {
        "form": form, "error": error, "catalogo": _catalogo(), "caja": caja, "items_previos": previos,
        "bc": BC,
    })


def _reponer(clave):
    """Líneas iniciales para «Armar compra» desde Reponer: lo que está en su mínimo de ese proveedor ("sin" = sin compras
    anteriores), con la cantidad y el costo de la última compra."""
    if not clave:
        return "[]"
    for g in s.reposicion():
        if (g["proveedor"].pk if g["proveedor"] else "sin") == (entero(clave) if clave != "sin" else "sin"):
            return json.dumps([{"variante": x["variante"].pk,
                                "cantidad": f"{x['ultima'].cantidad.normalize():f}" if x["ultima"] else "1",
                                "costo": f"{x['ultima'].costo_unitario.normalize():f}" if x["ultima"]
                                else (str(x["variante"].costo_efectivo) if x["variante"].costo_efectivo is not None else "")}
                               for x in g["items"]])
    return "[]"


@permiso_requerido("compras.ver")
def reponer(request):
    return render(request, "compras/reponer.html", {"grupos": s.reposicion()})


@permiso_requerido("compras.ver")
def detalle(request, pk):
    c = get_object_or_404(Compra.objects.select_related("proveedor", "usuario", "anulada_por"), pk=pk)
    caja = _caja_abierta(request.user)
    form = None
    if puede(request.user, "compras.pagar") and c.saldo:
        form = PagoForm(puede_caja=caja is not None, initial={"monto": c.saldo, "origen": "caja" if caja else "fuera",
                                                              "dia": timezone.localdate()})
    return render(request, "compras/detalle.html", {
        "c": c, "items": c.items.select_related("variante__producto"), "form": form, "caja": caja,
        "pagos": c.pagos.select_related("sesion", "usuario", "anulado_por").order_by("fecha"),
    })


def _pagar(request, pagar_fn, volver):
    caja = _caja_abierta(request.user)
    form = PagoForm(request.POST, puede_caja=caja is not None)
    if form.is_valid():
        d = form.cleaned_data
        try:
            pagar_fn(d["monto"], d["origen"], d["dia"] if d["origen"] == "fuera" else None)
            messages.success(request, f"Pago de S/ {d['monto']:.2f} registrado.")
        except s.CompraError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Revisa el monto y de dónde sale el pago.")
    return redirect(volver)


@permiso_requerido("compras.pagar")
@require_POST
def pagar(request, pk):
    c = get_object_or_404(Compra, pk=pk)
    return _pagar(request, lambda monto, origen, dia: s.pagar(c, monto, request.user, origen, dia), reverse("compras:detalle", args=[pk]))


@permiso_requerido("compras.pagar")
@require_POST
def pagar_proveedor(request, pk):
    p = get_object_or_404(Proveedor, pk=pk)
    volver = url_segura(request, request.POST.get("next"), reverse("compras:proveedor", args=[pk]))
    return _pagar(request, lambda monto, origen, dia: s.pagar_proveedor(p, monto, request.user, origen, dia), volver)


@permiso_requerido("compras.anular")
@require_POST
def anular(request, pk):
    c = get_object_or_404(Compra, pk=pk)
    try:
        s.anular_compra(c, request.user, request.POST.get("motivo"))
        con_caja = c.pagos.filter(anulado=False, sesion__isnull=False).exists()
        messages.success(request, "Compra anulada: se sacó del stock lo que había sumado."
                         + (" Lo que se pagó desde la caja no vuelve solo: registra el reembolso del proveedor como ingreso en tu caja."
                            if con_caja else ""))
    except s.CompraError as e:
        messages.error(request, str(e))
    return redirect("compras:detalle", pk=pk)


@permiso_requerido("compras.ver")
def proveedores(request):
    q = " ".join(request.GET.get("q", "").split())
    qs = Proveedor.objects.all()
    if q:
        from django.db.models import Q

        qs = qs.filter(Q(nombre__icontains=q) | Q(comercial__icontains=q) | Q(ruc__startswith=q) | Q(contacto__icontains=q))
    if request.GET.get("ver") != "todos":
        qs = qs.filter(activo=True)
    deudas = {d["proveedor"].pk: d for d in s.deudas_por_proveedor()}
    lista = list(qs)
    for p in lista:
        p.d = deudas.get(p.pk)
    lista.sort(key=lambda p: (-(p.d["deuda"] if p.d else 0), p.nombre.lower()))
    return render(request, "compras/proveedores.html", {"lista": lista, "q": q, "ver": request.GET.get("ver", "")})


@permiso_requerido("compras.ver")
def proveedor(request, pk=None):
    p = get_object_or_404(Proveedor, pk=pk) if pk else None
    editar = puede(request.user, "compras.registrar")
    if p is None and not editar:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    form = ProveedorForm(request.POST or None, instance=p, initial={"activo": True}) if editar else None
    if request.method == "POST" and editar and form.is_valid():
        p = form.save()
        messages.success(request, f"Proveedor {p} guardado.")
        siguiente = request.GET.get("next")
        if siguiente:
            sep = "&" if "?" in siguiente else "?"
            return redirect(url_segura(request, f"{siguiente}{sep}proveedor={p.pk}", reverse("compras:proveedor", args=[p.pk])))
        return redirect("compras:proveedor", pk=p.pk)
    ctx = {"p": p, "form": form}
    if p:
        caja = _caja_abierta(request.user)
        compras = list(s.con_pagado(p.compras.all()).order_by("-fecha", "-id")[:30])
        deuda = sum((c.saldo for c in s.con_saldo().filter(proveedor=p)), CERO)
        ctx.update({"compras": compras, "deuda": deuda, "caja": caja,
                    "pago": PagoForm(puede_caja=caja is not None, initial={"monto": deuda, "origen": "caja" if caja else "fuera",
                                                                          "dia": timezone.localdate()})
                    if deuda and puede(request.user, "compras.pagar") else None})
    return render(request, "compras/proveedor.html", ctx)


@permiso_requerido("compras.ver")
def por_pagar(request):
    return render(request, "compras/por_pagar.html", {
        "deudas": s.deudas_por_proveedor(), "compras": list(s.con_saldo()[:200]), "hoy": timezone.localdate(),
    })
