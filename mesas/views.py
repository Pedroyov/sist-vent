import json
from urllib.parse import quote

from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import entero

from .models import Cuenta, ItemCuenta, Mesa, Zona
from .servicios import MesaError, abrir_cuenta, agregar, anular_cuenta, cambiar_cantidad, cobrar, enviar_cocina, juntar, mover, quitar


def _abiertas():
    return Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA).select_related("mesa", "mozo").prefetch_related(
        Prefetch("items", queryset=ItemCuenta.objects.filter(anulado=False), to_attr="vigentes"))


def _datos_mapa():
    cuentas = {c.mesa_id: c for c in _abiertas() if c.mesa_id}
    zonas = []
    for z in Zona.objects.prefetch_related(Prefetch("mesas", queryset=Mesa.objects.filter(activa=True))):
        mesas = list(z.mesas.all())
        for m in mesas:
            m.cuenta = cuentas.get(m.pk)
            if m.cuenta:
                m.cuenta.total = sum((i.subtotal for i in m.cuenta.vigentes), 0)
                m.cuenta.sin_enviar = sum(1 for i in m.cuenta.vigentes if not i.enviado_en)
        if mesas:
            zonas.append({"zona": z, "mesas": mesas, "libres": sum(1 for m in mesas if not m.cuenta)})
    llevar = [c for c in _abiertas() if not c.mesa_id]
    for c in llevar:
        c.total = sum((i.subtotal for i in c.vigentes), 0)
        c.sin_enviar = sum(1 for i in c.vigentes if not i.enviado_en)
    return {"zonas": zonas, "llevar": llevar, "ahora": timezone.now()}


@permiso_requerido("mesas.atender", "mesas.cobrar")
def mapa(request):
    datos = _datos_mapa()
    if request.htmx:
        return render(request, "mesas/partials/mapa.html", datos)
    datos["hay_mesas"] = Mesa.objects.exists()
    return render(request, "mesas/mapa.html", datos)


@permiso_requerido("mesas.atender")
@require_POST
def abrir(request):
    mesa = get_object_or_404(Mesa, pk=entero(request.POST.get("mesa"))) if request.POST.get("mesa") else None
    try:
        cuenta = abrir_cuenta(request.user, mesa, entero(request.POST.get("personas")) or 1, request.POST.get("nombre", ""))
    except MesaError as e:
        messages.error(request, str(e))
        ocupada = mesa and mesa.cuentas.filter(estado=Cuenta.Estado.ABIERTA).first()
        return redirect("mesas:cuenta", pk=ocupada.pk) if ocupada else redirect("mesas:mapa")
    return redirect(reverse("mesas:agregar", args=[cuenta.pk]))


def _cuenta(pk):
    return get_object_or_404(Cuenta.objects.select_related("mesa__zona", "mozo"), pk=pk)


@permiso_requerido("mesas.atender", "mesas.cobrar")
def cuenta(request, pk):
    c = _cuenta(pk)
    items = list(c.items.select_related("agregado_por", "venta").order_by("creado", "id"))
    por_enviar = [i for i in items if not i.anulado and not i.enviado_en and not i.venta_id]
    enviados = [i for i in items if not i.anulado and i.enviado_en and not i.venta_id]
    pagados = [i for i in items if i.venta_id]
    anulados = [i for i in items if i.anulado]
    recien = parse_datetime(request.GET.get("enviado", "") or "")
    from caja.servicios import CajaError, sesion_para_vender

    try:
        sesion_para_vender(request.user)
        falta_caja = False
    except CajaError:
        falta_caja = True
    return render(request, "mesas/cuenta.html", {
        "c": c, "por_enviar": por_enviar, "enviados": enviados, "pagados": pagados, "anulados": anulados,
        "pendiente": sum((i.subtotal for i in por_enviar + enviados), 0),
        "ventas": sorted({i.venta for i in pagados}, key=lambda v: v.numero),
        "recien": [i for i in enviados if recien and i.enviado_en == recien],
        "recien_ts": request.GET.get("enviado", ""),
        "falta_caja": falta_caja and puede(request.user, "mesas.cobrar"),
        "puede_anular": puede(request.user, "mesas.anular"),
    })


@permiso_requerido("mesas.atender")
def agregar_vista(request, pk):
    c = _cuenta(pk)
    if request.method == "POST":
        try:
            datos = json.loads(request.body or b"{}")
            agregar(c, datos.get("items") or [], request.user)
        except (ValueError, AttributeError):
            return JsonResponse({"error": "Datos no válidos."}, status=400)
        except MesaError as e:
            return JsonResponse({"error": str(e)}, status=400)
        if datos.get("enviar"):
            ts = enviar_cocina(c)
            url = reverse("mesas:cuenta", args=[c.pk]) + (f"?enviado={quote(ts.isoformat())}" if ts else "")
        else:
            url = reverse("mesas:cuenta", args=[c.pk])
        return JsonResponse({"ok": True, "url": url})
    if not c.abierta:
        return redirect("mesas:cuenta", pk=pk)
    from productos.models import Categoria
    from ventas.views import _catalogo

    categorias = Categoria.objects.filter(activa=True, productos__activo=True).distinct()
    return render(request, "mesas/agregar.html", {"c": c, "catalogo": _catalogo(),
                                                  "categorias": [{"id": x.pk, "n": x.nombre} for x in categorias]})


def _accion(request, pk, funcion, ok=None):
    c = _cuenta(pk)
    try:
        resultado = funcion(c)
        if ok:
            messages.success(request, ok)
        return c, resultado
    except MesaError as e:
        messages.error(request, str(e))
        return c, None


@permiso_requerido("mesas.atender")
@require_POST
def enviar(request, pk):
    c, ts = _accion(request, pk, enviar_cocina)
    if ts:
        return redirect(reverse("mesas:cuenta", args=[pk]) + f"?enviado={quote(ts.isoformat())}")
    if ts is None and c.abierta:
        messages.info(request, "No había nada nuevo para enviar.")
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender")
@require_POST
def item(request, pk):
    it = get_object_or_404(ItemCuenta.objects.select_related("cuenta"), pk=pk)
    accion = request.POST.get("accion")
    try:
        if accion in ("mas", "menos"):
            cambiar_cantidad(it, 1 if accion == "mas" else -1)
        elif accion == "quitar":
            quitar(it, request.user, request.POST.get("motivo"), puede(request.user, "mesas.anular"))
            messages.success(request, "Producto quitado.")
    except MesaError as e:
        messages.error(request, str(e))
    return redirect("mesas:cuenta", pk=it.cuenta_id)


@permiso_requerido("mesas.atender")
@require_POST
def pedir_cuenta(request, pk):
    c = _cuenta(pk)
    if c.abierta:
        c.pidio_cuenta = not c.pidio_cuenta
        c.save(update_fields=["pidio_cuenta"])
    if c.pidio_cuenta:
        return redirect("mesas:precuenta", pk=pk)
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender", "mesas.cobrar")
def precuenta(request, pk):
    c = _cuenta(pk)
    return render(request, "mesas/precuenta.html", {"c": c, "items": c.por_cobrar().order_by("creado"), "total": c.total_por_cobrar})


@permiso_requerido("mesas.atender")
def comanda(request, pk):
    c = _cuenta(pk)
    ts = parse_datetime(request.GET.get("enviado", "") or "")
    items = c.items.filter(anulado=False, enviado_en__isnull=False)
    items = items.filter(enviado_en=ts) if ts else items
    return render(request, "mesas/comanda.html", {"c": c, "items": items, "ts": ts})


@permiso_requerido("mesas.atender")
def cambiar_mesa(request, pk):
    c = _cuenta(pk)
    if request.method == "POST":
        destino = get_object_or_404(Mesa, pk=entero(request.POST.get("mesa")))
        otra = destino.cuentas.filter(estado=Cuenta.Estado.ABIERTA).first()
        try:
            if otra:
                juntar(c, otra)
                messages.success(request, f"{c.titulo} se juntó con la mesa {destino.nombre}.")
                return redirect("mesas:cuenta", pk=otra.pk)
            mover(c, destino)
            messages.success(request, f"Se cambió a la mesa {destino.nombre}.")
        except MesaError as e:
            messages.error(request, str(e))
        return redirect("mesas:cuenta", pk=pk)
    datos = _datos_mapa()
    return render(request, "mesas/cambiar.html", {"c": c, **datos})


@permiso_requerido("mesas.cobrar")
@require_POST
def cobrar_vista(request, pk):
    c = _cuenta(pk)
    try:
        datos = json.loads(request.body or b"{}")
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Datos no válidos."}, status=400)
    try:
        venta = cobrar(c, request.user, datos.get("pagos") or [], [entero(i) for i in datos.get("items") or [] if entero(i)],
                       datos.get("propina") or 0, datos.get("cliente_nombre", ""), datos.get("cliente_documento", ""),
                       datos.get("nota", ""), str(datos.get("token") or "")[:40] or None)
    except MesaError as e:
        return JsonResponse({"error": str(e)}, status=400)
    c.refresh_from_db()
    siguiente = reverse("mesas:mapa") if not c.abierta else reverse("mesas:cuenta", args=[c.pk])
    return JsonResponse({"ok": True, "url": reverse("ventas:ticket", args=[venta.pk]) + "?nueva=1&volver=" + siguiente})


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def anular(request, pk):
    c, _ = _accion(request, pk, lambda c: anular_cuenta(c, request.user, request.POST.get("motivo"), puede(request.user, "mesas.anular")))
    if not c.abierta or Cuenta.objects.get(pk=pk).estado != Cuenta.Estado.ABIERTA:
        messages.success(request, f"{c.titulo} liberada.")
        return redirect("mesas:mapa")
    return redirect("mesas:cuenta", pk=pk)


# --- Configuración ----------------------------------------------------------------

@permiso_requerido("mesas.configurar")
def configurar(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "zona":
            nombre = " ".join(request.POST.get("nombre", "").split())[:40]
            if nombre:
                _, nueva = Zona.objects.get_or_create(nombre=nombre, defaults={"orden": Zona.objects.count() * 10})
                messages.success(request, f"Zona «{nombre}» creada." if nueva else "Esa zona ya existe.")
        elif accion == "lote":
            zona = get_object_or_404(Zona, pk=entero(request.POST.get("zona")))
            desde, hasta = entero(request.POST.get("desde")), entero(request.POST.get("hasta"))
            prefijo = request.POST.get("prefijo", "").strip()[:8]
            capacidad = entero(request.POST.get("capacidad")) or 4
            if desde is None or hasta is None or hasta < desde or hasta - desde > 100:
                messages.error(request, "Revisa los números (máximo 100 mesas a la vez).")
            else:
                creadas = 0
                for n in range(desde, hasta + 1):
                    _, nueva = Mesa.objects.get_or_create(nombre=f"{prefijo}{n}", defaults={"zona": zona, "capacidad": capacidad, "orden": n})
                    creadas += nueva
                messages.success(request, f"Se crearon {creadas} mesas." + (" Algunas ya existían." if creadas < hasta - desde + 1 else ""))
        elif accion == "mesa":
            m = get_object_or_404(Mesa, pk=entero(request.POST.get("pk")))
            nombre = request.POST.get("nombre", "").strip()[:20]
            if nombre and not Mesa.objects.filter(nombre=nombre).exclude(pk=m.pk).exists():
                m.nombre = nombre
            m.capacidad = entero(request.POST.get("capacidad")) or m.capacidad
            z = Zona.objects.filter(pk=entero(request.POST.get("zona"))).first()
            m.zona = z or m.zona
            m.activa = request.POST.get("activa") == "on"
            m.save()
            messages.success(request, f"Mesa {m.nombre} guardada.")
        elif accion == "borrar_mesa":
            m = get_object_or_404(Mesa, pk=entero(request.POST.get("pk")))
            if m.cuentas.exists():
                m.activa = False
                m.save(update_fields=["activa"])
                messages.info(request, f"La mesa {m.nombre} tiene historial: se desactivó.")
            else:
                m.delete()
                messages.success(request, "Mesa eliminada.")
        elif accion == "borrar_zona":
            z = get_object_or_404(Zona, pk=entero(request.POST.get("pk")))
            if z.mesas.exists():
                messages.error(request, "Primero quita o mueve las mesas de esa zona.")
            else:
                z.delete()
                messages.success(request, "Zona eliminada.")
        return redirect("mesas:configurar")
    zonas = Zona.objects.prefetch_related("mesas").annotate(n=Count("mesas"))
    return render(request, "mesas/configurar.html", {"zonas": zonas})
