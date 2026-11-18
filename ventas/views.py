import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import enlace_whatsapp, entero, url_segura
from productos.models import Categoria, GrupoOpciones, Opcion, Producto, Variante
from productos.servicios import minimo_disponible, ordenar_grupos

from .models import MetodoPago, Venta
from .servicios import VentaInvalida, anular_venta, registrar_venta, resumen

User = get_user_model()
MAX_CATALOGO = 5000


DIAS_MAS_VENDIDOS = 60


def mas_vendidos(dias=DIAS_MAS_VENDIDOS):
    """{producto_id: en cuántas ventas salió} en los últimos días (sin anuladas). Sirve para mostrar primero lo que más
    se vende: en Vender, en las mesas y en el delivery."""
    from .models import VentaItem

    desde = timezone.now() - timedelta(days=dias)
    filas = (VentaItem.objects.filter(venta__fecha__gte=desde).exclude(venta__estado=Venta.Estado.ANULADA)
             .values("variante__producto").annotate(n=Count("venta", distinct=True)))
    return {f["variante__producto"]: f["n"] for f in filas}


def _catalogo():
    """Productos activos con sus variantes, para buscar y vender sin ir al servidor en cada tecla.
    Van primero los más vendidos de los últimos 60 días; luego el resto por nombre."""
    productos = (Producto.objects.filter(activo=True).select_related("categoria")
                 .prefetch_related(Prefetch("variantes", queryset=Variante.objects.filter(activa=True), to_attr="vars"), "componentes",
                                   Prefetch("grupos", queryset=GrupoOpciones.objects.filter(activo=True).prefetch_related(
                                       Prefetch("opciones", queryset=Opcion.objects.filter(activa=True))), to_attr="grs"))
                 .order_by("nombre")[:MAX_CATALOGO])
    from core.models import Ajustes

    ajustes = Ajustes.cargar()
    veces = mas_vendidos()
    datos = []
    for p in sorted(productos, key=lambda p: (-veces.get(p.pk, 0), p.nombre.lower())):
        if not p.vars:
            continue
        datos.append({
            "id": p.pk, "n": p.nombre, "c": p.categoria_id, "s": p.es_servicio, "f": p.fraccionable,
            "u": "" if p.es_servicio else p.get_unidad_display().lower(), "img": p.imagen.url if p.imagen else "",
            "v": [{"id": v.pk, "n": v.nombre, "cod": v.codigo, "p": str(v.precio_venta),
                   "st": f"{v.stock.normalize():f}" if p.maneja_stock else None} for v in p.vars],
            "ag": p.agotado,
            "k": [{"id": c.pk, "n": c.nombre, "q": c.quitable, "g": c.cambiar_con_id} for c in p.componentes.all()] if ajustes.usa_lleva else [],
            "g": [{"id": g.pk, "n": g.nombre.removeprefix(f"{p.nombre}: "), "min": minimo_disponible(g), "max": g.maximo, "r": g.regla,
                   "o": [{"id": o.pk, "n": o.nombre, "p": str(o.precio), "ag": o.agotada, "d": o.por_defecto} for o in g.opciones.all()]}
                  for g in ordenar_grupos(p.grs)] if ajustes.usa_opciones or p.es_combo else [],
        })
    return datos


@permiso_requerido("ventas.vender")
def pos(request):
    categorias = Categoria.objects.filter(activa=True, productos__activo=True).distinct()
    from caja.servicios import CajaError, sesion_para_vender
    from core.models import Ajustes

    try:
        sesion_para_vender(request.user)
        falta_caja = False
    except CajaError:
        falta_caja = True
    agregar = [int(x) for x in request.GET.get("agregar", "").split(",") if x.strip().isdigit()][:10]
    citas, citas_texto, n_por_cobrar, atendio_inicial = [], "", 0, None
    personas_atienden = []
    if Ajustes.cargar().usa_atendio:  # función «Quién atendió»: el cajero elige a la persona del personal
        from personal.models import Persona

        personas_atienden = list(Persona.objects.filter(activo=True).only("pk", "nombre"))
    from core.permisos import modulo_activo

    if modulo_activo(request.user, "citas"):
        from citas.models import Cita
        from citas.servicios import contar_por_cobrar

        ids = [int(x) for x in request.GET.get("citas", "").split(",") if x.strip().isdigit()][:20]
        if ids:
            lista = list(Cita.objects.filter(pk__in=ids, estado=Cita.Estado.ATENDIDA, cobrada=False, servicio__isnull=False)
                         .select_related("profesional"))
            citas = [c.pk for c in lista]
            agregar = [c.servicio_id for c in lista] + agregar
            if lista:
                nombres = " + ".join(dict.fromkeys(c.nombre for c in lista))  # varias cuentas cobradas juntas: todos los nombres
                citas_texto = f"{nombres}: " + ", ".join(f"{c.servicio_nombre} ({c.profesional.nombre})" for c in lista)
                quienes = {c.profesional_id for c in lista}
                atendio_inicial = quienes.pop() if len(quienes) == 1 else None
        n_por_cobrar = contar_por_cobrar()
    return render(request, "ventas/pos.html", {
        "falta_caja": falta_caja,
        "catalogo": _catalogo(),
        "categorias": [{"id": c.pk, "n": c.nombre} for c in categorias],
        "puede_precio": puede(request.user, "ventas.precio"),
        "con_delivery": Ajustes.cargar().delivery_activo and puede(request.user, "delivery.atender"),
        # ?agregar=12,15 → llega con esos productos en la venta (por ejemplo, el servicio de una cita atendida)
        "agregar": agregar, "citas": citas, "citas_texto": citas_texto, "n_por_cobrar": n_por_cobrar,
        "personas_atienden": personas_atienden, "atendio_inicial": atendio_inicial,
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
    from django.db import transaction

    from facturacion.servicios import ComprobanteError, crear, enviar_seguro, preparar

    try:
        sol = preparar(datos)
        with transaction.atomic():  # si el comprobante no se puede armar, la venta tampoco se guarda
            venta = registrar_venta(
                request.user, datos.get("items") or [], datos.get("pagos") or [], datos.get("descuento") or 0,
                datos.get("cliente_nombre", ""), datos.get("cliente_documento", ""), datos.get("nota", ""),
                token=str(datos.get("token") or "")[:40] or None,
                puede_cambiar_precio=puede(request.user, "ventas.precio"), propina=datos.get("propina") or 0,
                cliente_id=entero(datos.get("cliente_id")), puede_fiar=puede(request.user, "clientes.fiar"),
                puede_exceder_limite=puede(request.user, "clientes.limite"),
            )
            comprobante = crear(venta, sol, request.user)
            if entero(datos.get("atendio")):
                from core.models import Ajustes
                from personal.models import Persona

                if Ajustes.cargar().usa_atendio:
                    venta.atendio_persona = Persona.objects.filter(pk=entero(datos.get("atendio")), activo=True).first()
                    venta.save(update_fields=["atendio_persona"])
            ids_citas = [entero(x) for x in (datos.get("citas") or []) if entero(x)][:20]
            if ids_citas:  # servicios de peluquería / spa que se cobraron en esta venta
                from citas.servicios import marcar_cobradas

                marcar_cobradas(ids_citas, venta)
    except (VentaInvalida, ComprobanteError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    enviar_seguro(comprobante)
    return JsonResponse({"ok": True, "numero": venta.numero_str, "url": reverse("ventas:ticket", args=[venta.pk]) + "?nueva=1",
                         "vuelto": str(venta.vuelto)})


def _puede_ver(user, venta):
    return puede(user, "ventas.ver") or venta.usuario_id == user.pk


@permiso_requerido("ventas.vender", "ventas.ver")
def ticket(request, pk):
    venta = get_object_or_404(Venta.objects.select_related("usuario", "anulada_por", "atendio", "cliente").prefetch_related("items", "pagos"), pk=pk)
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
    texto = "\n".join(lineas)
    volver = request.GET.get("volver", "")
    return render(request, "ventas/ticket.html", {
        "v": venta, "nueva": request.GET.get("nueva") == "1",
        "volver": url_segura(request, volver, ""),
        "wa_enlace": enlace_whatsapp(None, texto),  # elige a quién mandarlo
        "ver_costos": puede(request.user, "productos.costos"),
    })


@permiso_requerido("ventas.vender", "ventas.ver")
def imprimir(request, pk):
    venta = get_object_or_404(Venta.objects.select_related("usuario", "atendio").prefetch_related("items", "pagos"), pk=pk)
    if not _puede_ver(request.user, venta):
        raise PermissionDenied
    return render(request, "impresion/ticket.html", {"v": venta, "deuda": venta.cliente.saldo if venta.cliente_id and venta.fiado else None})


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
    cliente = entero(request.GET.get("cliente"))
    if cliente:
        ventas = ventas.filter(cliente_id=cliente)
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


@permiso_requerido("ventas.vender", "ventas.ver", "mesas.cobrar")
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
        v = anular_venta(venta, request.user, request.POST.get("motivo"))
        messages.success(request, f"Venta {venta.numero_str} anulada. Lo vendido volvió al stock.")
        if getattr(v, "cuenta_reabierta", None):
            messages.info(request, f"{v.cuenta_reabierta.titulo} volvió a quedar por cobrar.")
            return redirect("mesas:cuenta", pk=v.cuenta_reabierta.pk)
    except VentaInvalida as e:
        messages.error(request, str(e))
    return redirect("ventas:ticket", pk=pk)
