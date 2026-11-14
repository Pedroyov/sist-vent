from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.permisos import permiso_requerido, puede
from core.utils import entero, url_segura

from .forms import AbrirForm, CerrarForm, MovimientoForm
from .models import DENOMINACIONES, MovimientoCaja, SesionCaja
from .servicios import CajaError, abrir, calcular, cerrar, movimiento, resumen_guardado, total_conteo

User = get_user_model()


def _puede_ver(user, sesion):
    return sesion.usuario_id == user.pk or puede(user, "caja.ver")


@permiso_requerido("caja.usar", "caja.ver")
def mi_caja(request):
    sesion = SesionCaja.abierta_de(request.user)
    if sesion is None:
        if not puede(request.user, "caja.usar"):
            return redirect("caja:historial")
        ultima = SesionCaja.objects.filter(usuario=request.user, estado=SesionCaja.Estado.CERRADA).first()
        form = AbrirForm(request.POST or None, initial={"monto_inicial": ultima.contado if ultima and ultima.contado is not None else None})
        if request.method == "POST" and form.is_valid():
            try:
                abrir(request.user, form.cleaned_data["monto_inicial"], form.cleaned_data["nota"])
                messages.success(request, "Caja abierta. ¡Buenas ventas!")
            except CajaError as e:
                messages.error(request, str(e))
            return redirect(url_segura(request, request.GET.get("next"), reverse("caja:mi_caja")))
        return render(request, "caja/abrir.html", {"form": form, "ultima": ultima})
    return redirect("caja:sesion", pk=sesion.pk)


@permiso_requerido("caja.usar", "caja.ver")
def sesion(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario", "cerrada_por"), pk=pk)
    if not _puede_ver(request.user, s):
        raise PermissionDenied
    r = calcular(s) if s.abierta else resumen_guardado(s)
    return render(request, "caja/sesion.html", {
        "s": s, "r": r, "movimientos": s.movimientos.select_related("usuario"),
        "es_mia": s.usuario_id == request.user.pk,
        "puede_operar": s.abierta and (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")),
        "conteo": [(d, s.conteo.get(d)) for d in DENOMINACIONES if s.conteo.get(d)],
    })


@permiso_requerido("caja.usar", "caja.ver")
def imprimir(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario"), pk=pk)
    if not _puede_ver(request.user, s):
        raise PermissionDenied
    r = calcular(s) if s.abierta else resumen_guardado(s)
    return render(request, "impresion/cierre_caja.html", {
        "s": s, "r": r, "movimientos": s.movimientos.order_by("fecha"),
        "conteo": [(d, s.conteo.get(d)) for d in DENOMINACIONES if s.conteo.get(d)]})


@permiso_requerido("caja.usar", "caja.ver")
def nuevo_movimiento(request, pk, tipo):
    s = get_object_or_404(SesionCaja, pk=pk, estado=SesionCaja.Estado.ABIERTA)
    if not (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")):
        raise PermissionDenied
    tipo = MovimientoCaja.Tipo.INGRESO if tipo == "ingreso" else MovimientoCaja.Tipo.EGRESO
    form = MovimientoForm(request.POST or None, tipo=tipo)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            movimiento(s, tipo, d["monto"], d["concepto"], request.user, d["categoria"])
            messages.success(request, f"{MovimientoCaja.Tipo(tipo).label} de S/ {d['monto']:.2f} registrado.")
        except CajaError as e:
            messages.error(request, str(e))
        return redirect("caja:sesion", pk=s.pk)
    titulo = "Ingreso de dinero" if tipo == MovimientoCaja.Tipo.INGRESO else "Salida de dinero (egreso)"
    url = reverse("caja:sesion", args=[s.pk])
    return render(request, "core/form.html", {"form": form, "titulo": titulo, "cancelar": url,
                                              "breadcrumb": [("Caja", url)], "subtitulo": f"Caja {s.numero}"})


@permiso_requerido("caja.usar", "caja.ver")
def cerrar_caja(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario"), pk=pk)
    if not (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")):
        raise PermissionDenied
    if not s.abierta:
        return redirect("caja:sesion", pk=pk)
    r = calcular(s)
    form = CerrarForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        total, conteo = total_conteo({d: request.POST.get(f"d_{d}") for d in DENOMINACIONES})
        contado = form.cleaned_data["contado"]
        if conteo and total != contado:
            contado = total  # manda el conteo por billetes
        try:
            s = cerrar(s, contado, request.user, conteo, form.cleaned_data["nota"])
        except CajaError as e:
            messages.error(request, str(e))
            return redirect("caja:sesion", pk=pk)
        if s.diferencia == 0:
            messages.success(request, "Caja cerrada. ¡Cuadró exacto!")
        else:
            messages.warning(request, f"Caja cerrada con {'sobrante' if s.diferencia > 0 else 'faltante'} de S/ {abs(s.diferencia):.2f}.")
        return redirect("caja:sesion", pk=pk)
    return render(request, "caja/cerrar.html", {"s": s, "r": r, "form": form, "denominaciones": DENOMINACIONES})


@permiso_requerido("caja.ver")
def historial(request):
    cajas = SesionCaja.objects.select_related("usuario")
    usuario = entero(request.GET.get("usuario"))
    if usuario:
        cajas = cajas.filter(usuario_id=usuario)
    if request.GET.get("estado") in SesionCaja.Estado.values:
        cajas = cajas.filter(estado=request.GET["estado"])
    pagina = Paginator(cajas, 30).get_page(request.GET.get("page"))
    for s in pagina.object_list:
        s.r = calcular(s) if s.abierta else resumen_guardado(s)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "caja/historial.html", {
        "pagina": pagina, "query": query, "usuario": usuario, "estado": request.GET.get("estado", ""),
        "usuarios": User.objects.filter(cajas__isnull=False).distinct().order_by("first_name"),
        "abiertas": SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA).select_related("usuario"),
        "hoy": timezone.localdate(),
    })
