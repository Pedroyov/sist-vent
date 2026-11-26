import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import resolve
from django.views.decorators.http import require_POST

from core.permisos import puede
from core.utils import entero

from . import servicios as s
from .models import Trabajo

NOMBRES = {"ventas:imprimir": (Trabajo.Tipo.TICKET, "Ticket"), "mesas:comanda": (Trabajo.Tipo.COMANDA, "Comanda"),
           "mesas:precuenta": (Trabajo.Tipo.PRECUENTA, "Precuenta"), "caja:imprimir": (Trabajo.Tipo.CIERRE, "Cierre de caja"),
           "clientes:imprimir": (Trabajo.Tipo.OTRO, "Estado de cuenta"), "cobranzas:recibo": (Trabajo.Tipo.OTRO, "Recibo")}


def _puede_estacion(user):
    """La estación (PC de caja) entra con un usuario de caja o Administración: tiene que poder abrir todo lo que imprime."""
    if not puede(user, "caja.ver", "ventas.vender", "mesas.cobrar"):
        raise PermissionDenied


def _json(request):
    try:
        d = json.loads(request.body or b"{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


@login_required
def estacion(request):
    _puede_estacion(request.user)
    return render(request, "impresion_cola/estacion.html", {"activa": s.activa()})


@login_required
@require_POST
def siguiente(request):
    _puede_estacion(request.user)
    d = _json(request)
    if not d.get("clave"):
        return JsonResponse({"error": "Falta la clave de la estación."}, status=400)
    e = s.latido(d["clave"], request.user, str(d.get("nombre") or ""))
    t = s.tomar(e) if s.activa() else None
    return JsonResponse({"trabajo": {"id": t.pk, "url": t.url, "descripcion": t.descripcion, "copia": t.copia} if t else None})


@login_required
@require_POST
def listo(request):
    _puede_estacion(request.user)
    d = _json(request)
    e = s.latido(d.get("clave") or "", request.user)
    t = s.terminar(entero(d.get("id")), e, bool(d.get("ok")), str(d.get("error") or ""))
    return JsonResponse({"ok": t is not None})


@login_required
@require_POST
def enviar(request):
    """Imprimir → «Ticketera de caja»: desde cualquier equipo, a la cola de la estación (como copia)."""
    d = _json(request)
    url = str(d.get("url") or "")
    if not s.url_valida(url):
        return JsonResponse({"error": "Eso no se puede imprimir."}, status=400)
    m = resolve(url.split("?")[0])
    tipo, nombre = NOMBRES.get(f"{m.namespace}:{m.url_name}", (Trabajo.Tipo.OTRO, "Impresión"))
    pk = m.kwargs.get("pk")
    Trabajo.objects.create(tipo=tipo, url=url, descripcion=f"{nombre} {pk}" if pk else nombre, copia=True, creado_por=request.user)
    return JsonResponse({"ok": True, "estacion": s.hay_estacion()})


@login_required
def cola(request):
    """Lo que se mandó a imprimir: lo pendiente, lo que falló (para reimprimir) y lo último impreso."""
    _puede_estacion(request.user)
    if request.method == "POST":
        t = get_object_or_404(Trabajo, pk=entero(request.POST.get("trabajo")))
        if request.POST.get("accion") == "descartar":
            Trabajo.objects.filter(pk=t.pk).exclude(estado=Trabajo.Estado.IMPRESO).update(estado=Trabajo.Estado.ERROR, error="Descartado a mano")
            messages.info(request, f"«{t.descripcion}» ya no se imprimirá.")
        else:
            s.reimprimir(t, request.user)
            messages.success(request, f"«{t.descripcion}» se volverá a imprimir.")
        return redirect("impresion:cola")
    trabajos = list(Trabajo.objects.select_related("estacion", "creado_por").order_by("-creado", "-id")[:80])
    return render(request, "impresion_cola/cola.html", {"trabajos": trabajos, "estado": s.estado_cola(), "activa": s.activa()})
