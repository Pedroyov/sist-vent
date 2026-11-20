from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.permisos import permiso_requerido, puede
from core.utils import entero, url_segura

from .forms import AbrirForm, CerrarForm, GastoForm, MovimientoForm, PuntoCajaForm
from .models import DENOMINACIONES, MovimientoCaja, PuntoCaja, SesionCaja
from .servicios import (CajaError, abrir, anular_gasto, calcular, cerrar, gasto_fuera_de_caja, gastos, movimiento, resumen_guardado, sencillo_anterior,
                        total_conteo)

User = get_user_model()


def _puede_ver(user, sesion):
    return sesion.usuario_id == user.pk or puede(user, "caja.ver")


def _ciego(user, sesion):
    """Cierre ciego: mientras la caja está abierta, el cajero no ve cuánto efectivo debería haber (ni lo que suma lo vendido
    en efectivo); cuenta sin saberlo y la diferencia la calcula el sistema al cerrar. Quien supervisa (caja.ver) sí lo ve."""
    return sesion.abierta and not puede(user, "caja.ver")


@permiso_requerido("caja.usar", "caja.ver")
def mi_caja(request):
    sesion = SesionCaja.abierta_de(request.user)
    if sesion is None:
        if not puede(request.user, "caja.usar"):
            return redirect("caja:historial")
        ultima, dejado = sencillo_anterior(request.user)
        form = AbrirForm(request.POST or None, initial={"monto_inicial": dejado})
        if request.method == "POST" and form.is_valid():
            monto, nota = form.cleaned_data["monto_inicial"], form.cleaned_data["nota"]
            if dejado is not None and monto != dejado:  # no está lo que se dejó: queda anotado en la apertura
                nota = f"Se dejaron S/ {dejado:.2f} y se encontraron S/ {monto:.2f}. {nota}".strip()
            try:
                abrir(request.user, monto, nota, form.cleaned_data.get("punto"))
                messages.success(request, "Caja abierta. ¡Buenas ventas!")
            except CajaError as e:
                messages.error(request, str(e))
            return redirect(url_segura(request, request.GET.get("next"), reverse("caja:mi_caja")))
        return render(request, "caja/abrir.html", {"form": form, "ultima": ultima, "dejado": dejado})
    return redirect("caja:sesion", pk=sesion.pk)


@permiso_requerido("caja.usar", "caja.ver")
def sesion(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario", "cerrada_por"), pk=pk)
    if not _puede_ver(request.user, s):
        raise PermissionDenied
    r = calcular(s) if s.abierta else resumen_guardado(s)
    return render(request, "caja/sesion.html", {
        "s": s, "r": r, "movimientos": s.movimientos.select_related("usuario", "persona"),
        "es_mia": s.usuario_id == request.user.pk,
        "puede_operar": s.abierta and (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")),
        "conteo": [(d, s.conteo.get(d)) for d in DENOMINACIONES if s.conteo.get(d)], "ciego": _ciego(request.user, s),
    })


@permiso_requerido("caja.usar", "caja.ver")
def imprimir(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario"), pk=pk)
    if not _puede_ver(request.user, s):
        raise PermissionDenied
    r = calcular(s) if s.abierta else resumen_guardado(s)
    return render(request, "impresion/cierre_caja.html", {
        "s": s, "r": r, "movimientos": s.movimientos.order_by("fecha"), "ciego": _ciego(request.user, s),
        "conteo": [(d, s.conteo.get(d)) for d in DENOMINACIONES if s.conteo.get(d)]})


@permiso_requerido("caja.usar", "caja.ver")
def nuevo_movimiento(request, pk, tipo):
    s = get_object_or_404(SesionCaja, pk=pk, estado=SesionCaja.Estado.ABIERTA)
    if not (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")):
        raise PermissionDenied
    tipo = MovimientoCaja.Tipo.INGRESO if tipo == "ingreso" else MovimientoCaja.Tipo.EGRESO
    form = MovimientoForm(request.POST or None, tipo=tipo, initial=_inicial(request))
    url = reverse("caja:sesion", args=[s.pk])
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            movimiento(s, tipo, d["monto"], d["concepto"], request.user, d["categoria"], persona=d.get("persona"))
            messages.success(request, f"{MovimientoCaja.Tipo(tipo).label} de S/ {d['monto']:.2f} registrado.")
        except CajaError as e:
            messages.error(request, str(e))
        return redirect(url_segura(request, request.GET.get("next"), url))
    titulo = "Ingreso de dinero" if tipo == MovimientoCaja.Tipo.INGRESO else "Salida de dinero (egreso)"
    return render(request, "core/form.html", {"form": form, "titulo": titulo, "cancelar": url_segura(request, request.GET.get("next"), url),
                                              "breadcrumb": [("Caja", url)], "subtitulo": f"Caja {s.numero}"})


@permiso_requerido("caja.usar", "caja.ver")
def cerrar_caja(request, pk):
    s = get_object_or_404(SesionCaja.objects.select_related("usuario"), pk=pk)
    if not (s.usuario_id == request.user.pk or puede(request.user, "caja.ver")):
        raise PermissionDenied
    if not s.abierta:
        return redirect("caja:sesion", pk=pk)
    ciego = _ciego(request.user, s)
    r = calcular(s)
    form = CerrarForm(request.POST or None, initial={"queda": s.monto_inicial or None})
    if request.method == "POST" and form.is_valid():
        total, conteo = total_conteo({d: request.POST.get(f"d_{d}") for d in DENOMINACIONES})
        contado = form.cleaned_data["contado"]
        if conteo and total != contado:
            contado = total  # manda el conteo por billetes
        try:
            s = cerrar(s, contado, request.user, conteo, form.cleaned_data["nota"], form.cleaned_data["queda"])
        except CajaError as e:
            messages.error(request, str(e))
            return redirect("caja:cerrar", pk=pk)
        retiro = f" Retiras S/ {s.retirado:.2f} y dejas S/ {s.queda:.2f} en el cajón." if s.retirado else ""
        if ciego:
            messages.success(request, f"Caja cerrada. Contaste S/ {s.contado:.2f}.{retiro}")
        elif s.diferencia == 0:
            messages.success(request, f"Caja cerrada. ¡Cuadró exacto!{retiro}")
        else:
            messages.warning(request, f"Caja cerrada con {'sobrante' if s.diferencia > 0 else 'faltante'} de S/ {abs(s.diferencia):.2f}.{retiro}")
        return redirect("caja:sesion", pk=pk)
    return render(request, "caja/cerrar.html", {"s": s, "r": r, "form": form, "denominaciones": DENOMINACIONES, "ciego": ciego})


@permiso_requerido("caja.ver")
def historial(request):
    cajas = SesionCaja.objects.select_related("usuario", "punto")
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
        "abiertas": SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA).select_related("usuario", "punto"),
        "hoy": timezone.localdate(),
    })


def _inicial(request):
    """Datos que llegan por la URL (desde «Pagos al personal»: a quién, cuánto y por qué)."""
    g = request.GET
    return {k: g[k] for k in ("categoria", "persona", "monto", "concepto") if g.get(k)}


# --- Gastos: todo lo que salió (de las cajas y fuera de caja) -------------------------------

@permiso_requerido("caja.ver")
def lista_gastos(request):
    from reportes.servicios import ATAJOS, periodo

    desde, hasta, atajo = periodo(request, defecto="mes")
    C = MovimientoCaja.Categoria
    qs = (MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, fecha__date__gte=desde, fecha__date__lte=hasta)
          .select_related("sesion", "usuario", "persona", "anulado_por"))
    motivo = request.GET.get("motivo", "")
    if motivo in C.values:
        qs = qs.filter(categoria=motivo)
    persona = entero(request.GET.get("persona"))
    if persona:
        qs = qs.filter(persona_id=persona)
    query = request.GET.copy()
    query.pop("page", None)
    filtro = {k: v for k, v in query.items() if k in ("p", "desde", "hasta")}
    return render(request, "caja/gastos.html", {
        "desde": desde, "hasta": hasta, "atajo": atajo, "atajos": ATAJOS, "g": gastos(desde, hasta),
        "pagina": Paginator(qs, 50).get_page(request.GET.get("page")), "query": query, "motivo": motivo,
        "motivos": [(c.value, c.label.split(" (")[0]) for c in C], "persona": persona, "filtro": filtro,
    })


@permiso_requerido("caja.ver")
def gasto_nuevo(request):
    form = GastoForm(request.POST or None, initial={"dia": timezone.localdate(), **_inicial(request)})
    volver = url_segura(request, request.GET.get("next"), reverse("caja:gastos"))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            gasto_fuera_de_caja(d["monto"], d["concepto"], request.user, d["categoria"], d["dia"], d.get("persona"))
            messages.success(request, f"Gasto de S/ {d['monto']:.2f} registrado (fuera de caja).")
            return redirect(volver)
        except CajaError as e:
            form.add_error(None, str(e))
    return render(request, "core/form.html", {"form": form, "titulo": "Gasto pagado fuera de caja", "cancelar": volver,
                                              "breadcrumb": [("Gastos", reverse("caja:gastos"))],
                                              "ayuda": "Para lo que se pagó por transferencia, Yape o con dinero que no estaba en el cajón (alquiler, sueldos). Sale en los reportes pero no descuadra ninguna caja."})


@permiso_requerido("caja.ver")
def gasto_anular(request, pk):
    """Solo los de fuera de caja: los de una caja quedan en su cierre."""
    m = get_object_or_404(MovimientoCaja, pk=pk, sesion__isnull=True)
    if request.method == "POST":
        try:
            anular_gasto(m, request.user, request.POST.get("motivo"))
            messages.success(request, f"Se anuló el gasto «{m.concepto}».")
        except CajaError as e:
            messages.error(request, str(e))
    return redirect(url_segura(request, request.POST.get("next"), reverse("caja:gastos")))


# --- Cajas (puntos de cobro) y sus series -------------------------------------------------

@permiso_requerido("config.negocio")
def puntos(request):
    from facturacion.models import Config

    form = PuntoCajaForm(request.POST or None, initial={"activo": True})
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.orden = (PuntoCaja.objects.count() + 1) * 10
        p.save()
        messages.success(request, f"Caja «{p.nombre}» creada.")
        return redirect("caja:puntos")
    config = Config.cargar()
    lista = list(PuntoCaja.objects.all())
    for p in lista:
        p.series = [(nombre, p.serie(campo, config), bool(getattr(p, campo))) for nombre, campo in
                    [("Boletas", "serie_boleta"), ("Facturas", "serie_factura"), ("NC boletas", "serie_nc_boleta"), ("NC facturas", "serie_nc_factura")]]
        p.abierta_por = [s.usuario.first_name or s.usuario.username for s in p.sesiones.filter(estado=SesionCaja.Estado.ABIERTA).select_related("usuario")]
    return render(request, "caja/puntos.html", {"form": form, "puntos": lista, "config": config})


@permiso_requerido("config.negocio")
def punto_editar(request, pk):
    p = get_object_or_404(PuntoCaja, pk=pk)
    form = PuntoCajaForm(request.POST or None, instance=p)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Caja guardada.")
        return redirect("caja:puntos")
    return render(request, "core/form.html", {
        "form": form, "titulo": f"Caja {p.nombre}", "cancelar": reverse("caja:puntos"),
        "breadcrumb": [("Caja", reverse("caja:historial")), ("Cajas y series", reverse("caja:puntos"))],
        "ayuda": "Las series vacías usan las generales de Facturación. Las series nuevas también hay que registrarlas en tu proveedor (Nubefact).",
    })
