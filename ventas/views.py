import json
from datetime import date, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import entero
from productos.models import Categoria, Producto, Variante

from .models import MetodoPago, Venta
from .servicios import VentaInvalida, anular_venta, registrar_venta, resumen

User = get_user_model()
MAX_CATALOGO = 5000


def _catalogo():
    """Productos activos con sus variantes, para buscar y vender sin ir al servidor en cada tecla."""
    productos = (Producto.objects.filter(activo=True).select_related("categoria")
                 .prefetch_related(Prefetch("variantes", queryset=Variante.objects.filter(activa=True), to_attr="vars"))
                 .order_by("nombre")[:MAX_CATALOGO])
    datos = []
    for p in productos:
        if not p.vars:
            continue
        datos.append({
            "id": p.pk, "n": p.nombre, "c": p.categoria_id, "s": p.es_servicio, "f": p.fraccionable,
            "u": "" if p.es_servicio else p.get_unidad_display().lower(), "img": p.imagen.url if p.imagen else "",
            "v": [{"id": v.pk, "n": v.nombre, "cod": v.codigo, "p": str(v.precio_venta),
                   "st": f"{v.stock.normalize():f}" if p.maneja_stock else None} for v in p.vars],
        })
    return datos


@permiso_requerido("ventas.vender")
def pos(request):
    categorias = Categoria.objects.filter(activa=True, productos__activo=True).distinct()
    from caja.servicios import CajaError, sesion_para_vender

    try:
        sesion_para_vender(request.user)
        falta_caja = False
    except CajaError:
        falta_caja = True
    return render(request, "ventas/pos.html", {
        "falta_caja": falta_caja,
        "catalogo": _catalogo(),
        "categorias": [{"id": c.pk, "n": c.nombre} for c in categorias],
        "puede_precio": puede(request.user, "ventas.precio"),
    })


@permiso_requerido("ventas.vender")
@require_POST
def registrar(request):
    try:
        datos = json.loads(request.body or b"{}")
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Datos no válidos."}, status=400)
    try:
        venta = registrar_venta(
            request.user, datos.get("items") or [], datos.get("pagos") or [], datos.get("descuento") or 0,
            datos.get("cliente_nombre", ""), datos.get("cliente_documento", ""), datos.get("nota", ""),
            token=str(datos.get("token") or "")[:40] or None,
            puede_cambiar_precio=puede(request.user, "ventas.precio"), propina=datos.get("propina") or 0,
        )
    except VentaInvalida as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"ok": True, "numero": venta.numero_str, "url": reverse("ventas:ticket", args=[venta.pk]) + "?nueva=1",
                         "vuelto": str(venta.vuelto)})


def _puede_ver(user, venta):
    return puede(user, "ventas.ver") or venta.usuario_id == user.pk


@permiso_requerido("ventas.vender", "ventas.ver")
def ticket(request, pk):
    venta = get_object_or_404(Venta.objects.select_related("usuario", "anulada_por", "atendio").prefetch_related("items", "pagos"), pk=pk)
    if not _puede_ver(request.user, venta):
        raise PermissionDenied
    from core.models import Ajustes

    negocio = Ajustes.cargar()
    lineas = [f"*{negocio.nombre_mostrar}*", f"Venta N° {venta.numero_str} · {timezone.localtime(venta.fecha):%d/%m/%Y %H:%M}", ""]
    for i in venta.items.all():
        lineas.append(f"{i.cantidad.normalize():f} x {i.descripcion} = S/ {i.subtotal}")
    if venta.descuento:
        lineas.append(f"Descuento: -S/ {venta.descuento}")
    lineas += ["", f"*Total: S/ {venta.total}*"]
    if venta.propina:
        lineas.append(f"Propina: S/ {venta.propina}")
    if negocio.nota_ticket:
        lineas += ["", negocio.nota_ticket]
    texto = quote("\n".join(lineas))
    volver = request.GET.get("volver", "")
    return render(request, "ventas/ticket.html", {
        "v": venta, "nueva": request.GET.get("nueva") == "1",
        "volver": volver if volver.startswith("/") and not volver.startswith("//") else "",
        "wa_texto": texto,
        "ver_costos": puede(request.user, "productos.costos"),
    })


@permiso_requerido("ventas.vender", "ventas.ver")
def imprimir(request, pk):
    venta = get_object_or_404(Venta.objects.select_related("usuario", "atendio").prefetch_related("items", "pagos"), pk=pk)
    if not _puede_ver(request.user, venta):
        raise PermissionDenied
    return render(request, "impresion/ticket.html", {"v": venta})


def _rango(request):
    hoy = timezone.localdate()
    try:
        desde = date.fromisoformat(request.GET.get("desde") or "")
    except ValueError:
        desde = hoy
    try:
        hasta = date.fromisoformat(request.GET.get("hasta") or "")
    except ValueError:
        hasta = desde if request.GET.get("desde") else hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    return desde, hasta


def _filtrar(request):
    desde, hasta = _rango(request)
    ventas = Venta.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta).select_related("usuario")
    solo_mias = not puede(request.user, "ventas.ver")
    usuario = entero(request.GET.get("usuario"))
    if solo_mias:
        ventas = ventas.filter(usuario=request.user)
    elif usuario:
        ventas = ventas.filter(usuario_id=usuario)
    caja = entero(request.GET.get("caja"))
    if caja:
        ventas = ventas.filter(sesion_caja_id=caja)
    metodo = request.GET.get("metodo", "")
    if metodo in MetodoPago.values:
        ventas = ventas.filter(pagos__metodo=metodo).distinct()
    estado = request.GET.get("estado", "")
    if estado in Venta.Estado.values:
        ventas = ventas.filter(estado=estado)
    q = request.GET.get("q", "").strip()
    if q:
        filtro = Q(cliente_nombre__icontains=q) | Q(cliente_documento__icontains=q) | Q(items__descripcion__icontains=q)
        if q.isdigit():
            filtro |= Q(numero=int(q))
        ventas = ventas.filter(filtro).distinct()
    f = {"caja": caja, "desde": desde, "hasta": hasta, "usuario": usuario, "metodo": metodo, "estado": estado, "q": q, "solo_mias": solo_mias}
    return ventas, f


@permiso_requerido("ventas.vender", "ventas.ver")
def lista(request):
    ventas, f = _filtrar(request)
    if request.GET.get("excel"):
        return _excel(ventas.prefetch_related("pagos"))
    r = resumen(ventas)
    pagina = Paginator(ventas.prefetch_related("pagos"), 40).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    hoy = timezone.localdate()
    return render(request, "ventas/lista.html", {
        "pagina": pagina, "f": f, "r": r, "query": query, "metodos": MetodoPago.choices, "estados": Venta.Estado.choices,
        "usuarios": User.objects.filter(ventas__isnull=False).distinct().order_by("first_name") if not f["solo_mias"] else [],
        "atajos": [("Hoy", hoy, hoy), ("Ayer", hoy - timedelta(days=1), hoy - timedelta(days=1)),
                   ("7 días", hoy - timedelta(days=6), hoy), ("Este mes", hoy.replace(day=1), hoy)],
        "ver_costos": puede(request.user, "productos.costos") and not f["solo_mias"],
    })


def _excel(ventas):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core.excel import a_bytes

    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["N°", "Fecha", "Hora", "Estado", "Cliente", "DNI/RUC", "Subtotal", "Descuento", "Total", "Pagos", "Vendedor", "Motivo anulación"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for v in ventas[:50000]:
        f = timezone.localtime(v.fecha)
        ws.append([v.numero_str, f.strftime("%d/%m/%Y"), f.strftime("%H:%M"), v.get_estado_display(), v.cliente_nombre,
                   v.cliente_documento, float(v.subtotal), float(v.descuento), float(v.total),
                   ", ".join(f"{p.get_metodo_display()} {p.monto}" for p in v.pagos.all()),
                   v.usuario.get_full_name() or v.usuario.username, v.motivo_anulacion])
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"ventas_{timezone.localdate():%Y%m%d}.xlsx")
    return resp


@permiso_requerido("ventas.anular")
@require_POST
def anular(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    try:
        anular_venta(venta, request.user, request.POST.get("motivo"))
        messages.success(request, f"Venta {venta.numero_str} anulada. Lo vendido volvió al stock.")
    except VentaInvalida as e:
        messages.error(request, str(e))
    return redirect("ventas:ticket", pk=pk)
