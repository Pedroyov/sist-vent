from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.permisos import modulo_activo, permiso_requerido, puede
from core.utils import entero

from .forms import ConfigForm, ReservaForm
from .models import Config, Reserva
from .servicios import (ReservaError, cancelar, cerrar_pasadas, confirmar, del_dia, enlace_whatsapp, guardar, llego, no_vino,
                        reabrir, resumen_dia)


def _puede_llegada(user):
    """Marcar «Llegaron» o «No vino»: quien gestiona reservas, o quien atiende mesas (el mozo que los recibe)."""
    return puede(user, "reservas.gestionar") or (puede(user, "reservas.ver") and puede(user, "mesas.atender"))


def _destino(request, r):
    sig = request.POST.get("next") or request.GET.get("next")
    if sig and url_has_allowed_host_and_scheme(sig, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return sig
    return f"{reverse('reservas:agenda')}?fecha={r.fecha:%Y-%m-%d}"


@permiso_requerido("reservas.ver")
def agenda(request):
    cerrar_pasadas()
    hoy = timezone.localdate()
    ahora = timezone.now()
    cfg = Config.cargar()
    q = request.GET.get("q", "").strip()
    fecha = parse_date(request.GET.get("fecha") or "") or hoy
    if q:
        reservas = Reserva.objects.filter(fecha__gte=hoy - timedelta(days=30)).select_related("mesa", "creada_por", "cuenta")
        for palabra in q.split():
            reservas = reservas.filter(Q(nombre__icontains=palabra) | Q(telefono__icontains=palabra) | Q(nota__icontains=palabra))
        reservas = list(reservas.order_by("-fecha", "hora")[:50])
    else:
        reservas = list(del_dia(fecha))
    if request.GET.get("excel"):
        from core.excel import descargar

        return descargar(f"reservas_{fecha:%Y%m%d}", [("Reservas", ["Fecha", "Hora", "Nombre", "Celular", "Personas", "Mesa", "Nota", "Estado"],
                                                       [[r.fecha, r.hora.strftime("%H:%M"), r.nombre, r.telefono, r.personas, str(r.mesa or ""),
                                                         r.nota, r.get_estado_display()] for r in reservas])])
    for r in reservas:
        r.es_atrasada = r.atrasada(ahora, cfg)
        r.wa = enlace_whatsapp(r, hoy) if r.activa else ""
    # activas primero (por hora), luego las que ya se cerraron
    if not q:
        reservas.sort(key=lambda r: (not r.activa, r.hora))
    proximos = []
    conteo = {f: (n, p) for f, n, p in Reserva.objects.filter(fecha__gte=hoy, fecha__lte=hoy + timedelta(days=13))
              .exclude(estado=Reserva.Estado.CANCELADA).values("fecha").annotate(n=Count("pk"), p=Sum("personas"))
              .values_list("fecha", "n", "p")}
    for i in range(14):
        f = hoy + timedelta(days=i)
        n, p = conteo.get(f, (0, 0))
        proximos.append({"fecha": f, "n": n, "personas": p or 0})
    con_mesas = modulo_activo(request.user, "mesas")
    libres = []
    if con_mesas and fecha == hoy and _puede_llegada(request.user):
        from mesas.models import Cuenta, Mesa

        ocupadas = set(Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA, mesa__isnull=False).values_list("mesa_id", flat=True))
        ocupadas |= set(Mesa.objects.filter(unida_a__estado=Cuenta.Estado.ABIERTA).values_list("pk", flat=True))
        libres = [m for m in Mesa.objects.filter(activa=True).select_related("zona") if m.pk not in ocupadas]
    return render(request, "reservas/agenda.html", {
        "reservas": reservas, "fecha": fecha, "hoy": hoy, "q": q, "r": resumen_dia(fecha), "proximos": proximos,
        "anterior": fecha - timedelta(days=1), "siguiente": fecha + timedelta(days=1), "manana": hoy + timedelta(days=1),
        "cfg": cfg, "con_mesas": con_mesas, "libres": libres, "puede_llegada": _puede_llegada(request.user),
        "nueva": entero(request.GET.get("nueva")),
    })


def _hora_sugerida(fecha):
    """Para hoy: la próxima media hora; otro día: 8:00 pm."""
    ahora = timezone.localtime()
    if fecha != ahora.date():
        return datetime.strptime("20:00", "%H:%M").time()
    m = (ahora + timedelta(minutes=30 - ahora.minute % 30)).replace(second=0, microsecond=0)
    return m.time() if m.date() == ahora.date() else ahora.time().replace(second=0, microsecond=0)


@permiso_requerido("reservas.gestionar")
def formulario(request, pk=None):
    r = get_object_or_404(Reserva.objects.select_related("mesa"), pk=pk) if pk else None
    if r is not None and not r.activa:
        messages.warning(request, f"Esta reserva ya está como «{r.get_estado_display()}»: no se puede cambiar.")
        return redirect(_destino(request, r))
    con_mesas = modulo_activo(request.user, "mesas")
    choque = False
    if request.method == "POST":
        form = ReservaForm(request.POST, con_mesas=con_mesas)
        if form.is_valid():
            d = form.cleaned_data
            try:
                r2, avisos = guardar(request.user, r, fecha=d["fecha"], hora=d["hora"], personas=d["personas"], nombre=d["nombre"],
                                     telefono=d["telefono"], mesas=list(d.get("mesas") or []), nota=d["nota"],
                                     permitir_choque=d["permitir_choque"])
            except ReservaError as e:
                form.add_error(None, str(e))
                choque = "ya está reservada" in str(e)
            else:
                messages.success(request, f"Reserva {'guardada' if r else 'tomada'}: {r2.nombre}, {r2.fecha:%d/%m} a las {r2.hora:%H:%M}, "
                                          f"{r2.personas} persona{'s' if r2.personas != 1 else ''}.")
                for a in avisos:
                    messages.warning(request, a)
                return redirect(f"{reverse('reservas:agenda')}?fecha={r2.fecha:%Y-%m-%d}&nueva={r2.pk}")
    elif r is not None:
        form = ReservaForm.desde(r, con_mesas=con_mesas)
    else:
        fecha = parse_date(request.GET.get("fecha") or "") or timezone.localdate()
        if fecha < timezone.localdate():
            fecha = timezone.localdate()
        inicial = {"fecha": fecha, "hora": _hora_sugerida(fecha), "personas": 2}
        if con_mesas and request.GET.get("mesa"):
            inicial["mesas"] = [entero(request.GET.get("mesa"))]
        form = ReservaForm(initial=inicial, con_mesas=con_mesas)
    mesas_zonas = []
    if con_mesas:
        from mesas.models import Zona

        for z in Zona.objects.prefetch_related("mesas"):
            lista = [m for m in z.mesas.all() if m.activa]
            if lista:
                mesas_zonas.append((z, lista))
    elegidas = {str(x) for x in (form["mesas"].value() or [])} if con_mesas else set()
    return render(request, "reservas/form.html", {"form": form, "r": r, "choque": choque, "mesas_zonas": mesas_zonas, "elegidas": elegidas,
                                                  "breadcrumb": [("Reservas", reverse("reservas:agenda"))]})


ACCIONES = {"confirmar": confirmar, "cancelar": cancelar, "no_vino": no_vino, "reabrir": reabrir}


@require_POST
@permiso_requerido("reservas.ver")
def accion(request, pk, accion):
    r = get_object_or_404(Reserva, pk=pk)
    if accion in ("llego", "no_vino"):
        if not _puede_llegada(request.user):
            raise PermissionDenied
    elif accion in ACCIONES:
        if not puede(request.user, "reservas.gestionar"):
            raise PermissionDenied
    else:
        raise PermissionDenied
    try:
        if accion == "llego":
            mesas = []
            ids = [entero(x) for x in request.POST.getlist("mesa") if entero(x)]
            if ids:
                from mesas.models import Mesa

                por_id = {m.pk: m for m in Mesa.objects.filter(pk__in=ids)}
                mesas = [por_id[i] for i in ids if i in por_id]
                propias = r.mesas
                if len(mesas) == 1 and mesas[0] in propias:  # tocó una de sus mesas en el mapa: se abren todas las de la reserva
                    mesas = mesas + [m for m in propias if m != mesas[0]]
            cuenta = llego(r, request.user, mesas=mesas)
            if cuenta is not None:
                cuenta.refresh_from_db()
                messages.success(request, f"Bienvenidos, {r.nombre}: se abrió la mesa {cuenta.nombres_mesas} para {r.personas}.")
                if r.aviso:
                    messages.warning(request, r.aviso)
                return redirect("mesas:cuenta", pk=cuenta.pk)
            messages.success(request, f"{r.nombre} llegó.")
        else:
            ACCIONES[accion](r, request.user)
            textos = {"confirmar": "confirmada", "cancelar": "cancelada", "no_vino": "marcada como «No vino»", "reabrir": "activa otra vez"}
            messages.success(request, f"Reserva de {r.nombre} {textos[accion]}.")
    except ReservaError as e:
        messages.error(request, str(e))
    return redirect(_destino(request, r))


@permiso_requerido("reservas.gestionar")
def configurar(request):
    cfg = Config.cargar()
    form = ConfigForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Configuración de reservas guardada.")
        return redirect("reservas:agenda")
    return render(request, "reservas/configurar.html", {"form": form, "breadcrumb": [("Reservas", reverse("reservas:agenda"))]})
