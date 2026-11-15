from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido
from core.utils import entero, url_segura

from .forms import ConfigForm
from .models import Comprobante, Config
from .servicios import ComprobanteError, crear, enviar_seguro, reenviar_pendientes, revisar_antes, solicitud


@permiso_requerido("facturacion.ver")
def lista(request):
    qs = Comprobante.objects.select_related("venta", "modifica").order_by("-id")
    estado, tipo, q = request.GET.get("estado", ""), request.GET.get("tipo", ""), request.GET.get("q", "").strip()
    if estado in Comprobante.Estado.values:
        qs = qs.filter(estado=estado)
    elif estado == "falta":
        qs = qs.filter(estado__in=[Comprobante.Estado.PENDIENTE, Comprobante.Estado.ENVIADO])
    if tipo in Comprobante.Tipo.values:
        qs = qs.filter(tipo=tipo)
    if q:
        partes = q.upper().split("-")
        filtro = Q(cliente_doc__icontains=q) | Q(cliente_nombre__icontains=q)
        if len(partes) == 2 and partes[1].isdigit():
            filtro |= Q(serie=partes[0], numero=int(partes[1]))
        elif q.isdigit():
            filtro |= Q(numero=int(q))
        qs = qs.filter(filtro)
    pagina = Paginator(qs, 40).get_page(request.GET.get("page"))
    pendientes = Comprobante.objects.filter(estado__in=[Comprobante.Estado.PENDIENTE, Comprobante.Estado.ENVIADO]).count()
    return render(request, "facturacion/lista.html", {
        "pagina": pagina, "estado": estado, "tipo": tipo, "q": q, "pendientes": pendientes, "config": Config.cargar(),
        "estados": Comprobante.Estado.choices, "tipos": Comprobante.Tipo.choices,
        "rechazados": Comprobante.objects.filter(estado=Comprobante.Estado.RECHAZADO, creado__gte=timezone.now() - timedelta(days=7)).count(),
    })


@permiso_requerido("facturacion.ver")
@require_POST
def reenviar(request):
    if request.POST.get("id"):
        c = get_object_or_404(Comprobante, pk=entero(request.POST.get("id")))
        enviar_seguro(c)
        c.refresh_from_db()
        (messages.success if c.estado == Comprobante.Estado.ACEPTADO else messages.warning)(request, f"{c.numero_str}: {c.get_estado_display()}. {c.mensaje}")
    else:
        ok, mal = reenviar_pendientes()
        messages.info(request, f"Reenviados: {ok}." + (f" Sin respuesta: {mal} (revisa el internet o el proveedor)." if mal else ""))
    from django.urls import reverse

    return redirect(url_segura(request, request.POST.get("next"), reverse("facturacion:lista")))


@permiso_requerido("facturacion.configurar")
def configurar(request):
    from core.models import Ajustes

    config = Config.cargar()
    form = ConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Facturación guardada.")
        return redirect("facturacion:configurar")
    return render(request, "facturacion/configurar.html", {"form": form, "config": config, "negocio": Ajustes.cargar()})


@permiso_requerido("ventas.ver", "ventas.vender", "mesas.cobrar")
@require_POST
def emitir_venta(request, pk):
    """Boleta o factura para una venta que se cobró con nota de venta (el cliente la pidió después)."""
    from ventas.models import Venta

    v = get_object_or_404(Venta, pk=pk)
    volver = redirect("ventas:ticket", pk=pk)
    if v.anulada or v.comprobantes.exclude(tipo=Comprobante.Tipo.NOTA_CREDITO).exclude(estado=Comprobante.Estado.RECHAZADO).exists():
        messages.error(request, "Esta venta ya tiene comprobante o está anulada.")
        return volver
    if timezone.localdate(v.fecha) < timezone.localdate() - timedelta(days=2):
        messages.error(request, "Solo se puede emitir el comprobante de ventas de los últimos días.")
        return volver
    sol = solicitud({k: request.POST.get(k) for k in ("tipo", "doc", "nombre", "direccion")})
    if not sol:
        messages.error(request, "Elige boleta o factura.")
        return volver
    try:
        revisar_antes(sol, v.fiado)
        with transaction.atomic():
            c = crear(v, sol, request.user)
    except ComprobanteError as e:
        messages.error(request, str(e))
        return volver
    c = enviar_seguro(c)
    messages.success(request, f"{c.get_tipo_display()} {c.numero_str}: {c.get_estado_display().lower()}.")
    return volver
