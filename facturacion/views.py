from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido
from core.utils import dias, entero, url_segura

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
        from core.bitacora import anotar, cambios_form

        cambio = cambios_form(form, ocultos=("token",))
        form.save()
        if cambio:
            anotar("config.facturacion", f"Facturación: {', '.join(cambio)}", antes={k: v[0] for k, v in cambio.items()},
                   despues={k: v[1] for k, v in cambio.items()})
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


@permiso_requerido("facturacion.ver")
def excel_contador(request):
    """Registro de ventas del mes para el contador: cada comprobante con sus montos, forma de pago y si ya se cobró.
    Otra hoja con lo que el negocio marcó como incobrable."""
    from datetime import date

    from django.http import HttpResponse
    from django.utils.http import content_disposition_header
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from clientes.models import Abono
    from clientes.servicios import deudas
    from core.excel import a_bytes, como_texto

    hoy = timezone.localdate()
    try:
        anio, mes = (int(x) for x in (request.GET.get("mes") or f"{hoy:%Y-%m}").split("-"))
        desde = date(anio, mes, 1)
    except (TypeError, ValueError):
        desde = hoy.replace(day=1)
    hasta = (desde.replace(day=28) + timedelta(days=4)).replace(day=1)
    comps = list(Comprobante.objects.filter(fecha__gte=desde, fecha__lt=hasta).select_related("venta__cliente", "modifica").order_by("fecha", "serie", "numero"))
    pend = {}
    for cl in {c.venta.cliente for c in comps if c.al_credito and c.venta.cliente_id}:
        for d in deudas(cl):
            pend[d["venta"].pk] = d["pendiente"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Registro de ventas"
    ws.append(["Fecha", "Tipo", "Serie", "Número", "Tipo doc.", "Documento", "Cliente", "Op. gravada", "Op. exonerada", "Op. inafecta",
               "IGV", "Total", "Forma de pago", "Vence", "Pendiente de cobro", "Estado SUNAT", "Modifica a", "Venta anulada"])
    for c in comps:
        signo = -1 if c.es_nota else 1
        pendiente = pend.get(c.venta_id, 0) if c.al_credito else 0
        ws.append([c.fecha, c.get_tipo_display(), c.serie, c.numero, c.cliente_tipo_doc, c.cliente_doc, c.cliente_nombre or "CLIENTES VARIOS",
                   float(c.gravada) * signo, float(c.exonerada) * signo, float(c.inafecta) * signo, float(c.igv) * signo, float(c.total) * signo,
                   "Crédito" if c.al_credito else "Contado", c.vence, float(pendiente), c.get_estado_display(),
                   c.modifica.numero_str if c.modifica_id else "", "Sí" if c.venta.anulada else ""])
    ws2 = wb.create_sheet("Incobrables")
    ws2.append(["Fecha", "Cliente", "Documento", "Monto", "Motivo", "Marcado por"])
    for a in Abono.objects.filter(metodo="INC", anulado=False, **dias("fecha", desde, antes_de=hasta)).select_related("cliente", "usuario"):
        ws2.append([timezone.localtime(a.fecha).replace(tzinfo=None), a.cliente.nombre, a.cliente.documento, float(a.monto),
                    a.nota.removeprefix("Incobrable: "), a.usuario.get_full_name() or a.usuario.username])
    for hoja in (ws, ws2):
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        for fila in hoja.iter_rows(min_row=2):
            for celda in fila:
                como_texto(celda)
                if isinstance(celda.value, (date,)):
                    celda.number_format = "DD/MM/YYYY"
        for col in hoja.columns:
            hoja.column_dimensions[col[0].column_letter].width = 16
    r = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = content_disposition_header(True, f"registro_ventas_{desde:%Y-%m}.xlsx")
    return r
