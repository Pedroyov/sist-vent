from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from clientes.models import Cliente
from clientes.servicios import ClienteError, resolver_cliente
from core.permisos import permiso_requerido, puede
from core.utils import dias

from .forms import ConfigForm, EditarInscripcionForm, InscripcionForm, PlanForm
from .models import CERO, Asistencia, Config, Congelamiento, Cuota, Inscripcion, Pago, PagoCuota, Plan
from .servicios import (CobranzaError, adelantar, agrupar_por_cliente, al_dia, anular_pago, cambiar_precio, cobrar, codigo_carne,
                        congelar, dar_baja, descongelar, dias_congelados, enlace_whatsapp, estado_ingreso, exonerar, inscribir,
                        para_ingreso, pendientes, por_codigo, por_vencer, quitar_mora, reactivar, registrar_ingreso, resumen, vencidas)

BC = ("Cobranzas", "cobranzas:inicio")


def _bc():
    return [(BC[0], reverse(BC[1]))]


def _excel(nombre, encabezados, filas):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core.excel import a_bytes

    wb = Workbook()
    ws = wb.active
    ws.title = nombre[:30]
    ws.append(encabezados)
    for c in ws[1]:
        c.font = Font(bold=True)
    for f in filas:
        ws.append(f)
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"{nombre.lower().replace(' ', '_')}_{timezone.localdate():%Y%m%d}.xlsx")
    return resp


# --- Inicio ---------------------------------------------------------------------------

@permiso_requerido("cobranzas.ver")
def inicio(request):
    al_dia()
    hoy = timezone.localdate()
    if not Plan.objects.exists() and puede(request.user, "cobranzas.gestionar"):
        messages.info(request, "Empieza creando tus planes (por ejemplo: «Mensual», «Curso de 6 meses»).")
        return redirect("cobranzas:planes")
    morosos = agrupar_por_cliente(vencidas(hoy), hoy)
    proximos = agrupar_por_cliente(por_vencer(hoy), hoy)
    for g in morosos[:8] + proximos[:8]:
        g["wa"] = enlace_whatsapp(g["cliente"], g["cuotas"], hoy)
    return render(request, "cobranzas/inicio.html", {
        "r": resumen(hoy), "morosos": morosos[:8], "n_morosos": len(morosos), "proximos": proximos[:8], "n_proximos": len(proximos),
        "ultimos": Pago.objects.filter(anulado=False).select_related("cliente", "usuario")[:8],
        "cfg": Config.cargar(), "hoy": hoy,
    })


@permiso_requerido("cobranzas.ver")
def buscar(request):
    """Buscador rápido: lleva a la cuenta del cliente (por nombre, DNI, celular o nombre del alumno)."""
    q = request.GET.get("q", "").strip()
    resultados = []
    if len(q) >= 2:
        qs = Inscripcion.objects.select_related("cliente", "plan")
        for palabra in q.split():
            qs = qs.filter(Q(cliente__nombre__icontains=palabra) | Q(alumno__icontains=palabra)
                           | Q(cliente__numero_documento__startswith=palabra) | Q(cliente__telefono__icontains=palabra))
        vistos = set()
        for i in qs.order_by("estado", "cliente__nombre")[:30]:
            if i.cliente_id in vistos:
                continue
            vistos.add(i.cliente_id)
            resultados.append(i)
    return render(request, "cobranzas/partials/buscar.html", {"resultados": resultados[:10], "q": q})


# --- Cuenta de un cliente: sus inscripciones, cuotas y el cobro ----------------------

@permiso_requerido("cobranzas.ver")
def cuenta(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    al_dia()
    hoy = timezone.localdate()
    inscripciones = list(c.inscripciones.select_related("plan").order_by("estado", "-inicio"))
    cuotas = list(Cuota.objects.filter(inscripcion__cliente=c).select_related("inscripcion__plan").order_by("vence", "numero"))
    por_insc = {}
    for q in cuotas:
        por_insc.setdefault(q.inscripcion_id, []).append(q)
    for i in inscripciones:
        lista = por_insc.get(i.pk, [])
        i.lista_cuotas = lista
        # las ya cerradas (pagadas o exoneradas) más antiguas se esconden: se ven las 3 últimas y todo lo pendiente
        cerradas = [q for q in lista if q.pendiente == 0]
        for q in cerradas[:-3]:
            q.oculta = True
        i.n_ocultas = max(0, len(cerradas) - 3)
        i.debe = sum((q.pendiente for q in lista), CERO)
        i.vencido = sum((q.pendiente for q in lista if q.vencida(hoy)), CERO)
    pend = list(pendientes(c))
    wa_cuotas = [q for q in pend if q.vence <= hoy + timedelta(days=Config.cargar().dias_aviso)] or pend[:3]
    from core.models import Ajustes
    from ventas.models import MetodoPago

    aj = Ajustes.cargar()
    aceptados = aj.metodos_aceptados
    cfg = Config.cargar()
    if aj.usa_ingreso or cfg.congelar_dias:  # gimnasio: hasta cuándo puede entrar, sus ingresos y congelamientos
        extra = {x.pk: x for x in para_ingreso(c.inscripciones.all())}
        for i in inscripciones:
            x = extra[i.pk]
            i.ingreso = estado_ingreso(x, hoy, cfg)
            i.congelamientos_lista = [g for g in x.congelamientos.all() if g.hasta >= hoy]
            i.ultimos_ingresos = list(x.asistencias.all()[:5])
            i.puede_congelar = (cfg.congelar_dias and i.estado != Inscripcion.Estado.BAJA
                                and not (i.plan.frecuencia == Plan.Frecuencia.UNICO and not i.plan.duracion_dias))
            i.congelo = dias_congelados(x, hoy.year)
    return render(request, "cobranzas/cuenta.html", {
        "cfg": cfg, "usa_ingreso": aj.usa_ingreso,
        "c": c, "inscripciones": inscripciones, "pendientes": pend, "hoy": hoy,
        "total": sum((q.falta for q in pend), CERO), "vencido": sum((q.falta for q in pend if q.vence < hoy), CERO),
        "pagos": c.pagos_cobranza.select_related("usuario").prefetch_related("detalles__cuota")[:30],
        "metodos": [(k, v) for k, v in MetodoPago.choices if k in aceptados and k not in (MetodoPago.CREDITO, MetodoPago.SALDO)],
        "wa": enlace_whatsapp(c, wa_cuotas, hoy) if wa_cuotas else "",
        "planes_activos": Plan.objects.filter(activo=True).exists(),
    })


@permiso_requerido("cobranzas.cobrar")
@require_POST
def cobrar_vista(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    try:
        p = cobrar(c, request.POST.getlist("cuota"), request.POST.get("monto"), request.POST.get("metodo"), request.user,
                   request.POST.get("nota"), request.POST.get("referencia"))
        messages.success(request, f"Cobrado S/ {p.monto:.2f} (recibo {p.numero}).")
        return redirect(reverse("cobranzas:cuenta", args=[pk]) + f"?recibo={p.pk}")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=pk)


@permiso_requerido("cobranzas.ver")
def recibo(request, pk):
    p = get_object_or_404(Pago.objects.select_related("cliente", "usuario"), pk=pk)
    from .servicios import pendientes as pend

    detalles = p.detalles.select_related("cuota__inscripcion__plan")
    queda = sum((q.falta for q in pend(p.cliente)), CERO)
    return render(request, "impresion/recibo_cobranza.html", {"p": p, "detalles": detalles, "queda": queda})


@permiso_requerido("cobranzas.gestionar")
@require_POST
def anular(request, pk):
    p = get_object_or_404(Pago, pk=pk)
    try:
        anular_pago(p, request.user, request.POST.get("motivo"))
        messages.success(request, f"Recibo {p.numero} anulado. Las cuotas vuelven a quedar pendientes.")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=p.cliente_id)


# --- Inscripciones -----------------------------------------------------------------

@permiso_requerido("cobranzas.ver")
def inscritos(request):
    al_dia()
    q = request.GET.get("q", "").strip()
    plan = request.GET.get("plan", "")
    estado = request.GET.get("estado", "ACT")
    qs = Inscripcion.objects.select_related("cliente", "plan")
    if estado in Inscripcion.Estado.values:
        qs = qs.filter(estado=estado)
    if plan.isdigit():
        qs = qs.filter(plan_id=plan)
    for palabra in q.split():
        qs = qs.filter(Q(cliente__nombre__icontains=palabra) | Q(alumno__icontains=palabra)
                       | Q(cliente__numero_documento__startswith=palabra) | Q(cliente__telefono__icontains=palabra))
    hoy = timezone.localdate()
    from .servicios import PENDIENTE

    deuda = {}
    for fila in (Cuota.objects.filter(inscripcion__in=qs, anulada=False).annotate(falta=PENDIENTE).filter(falta__gt=0)
                 .values("inscripcion_id").annotate(t=Sum("falta"), v=Sum("falta", filter=Q(vence__lt=hoy)))):
        deuda[fila["inscripcion_id"]] = fila
    qs = qs.order_by("cliente__nombre", "alumno")
    if request.GET.get("excel"):
        return _excel("Inscritos", ["Cliente", "Documento", "Celular", "Alumno o socio", "Plan", "Precio", "Empezó", "Estado", "Debe", "Vencido"],
                      [[i.cliente.nombre, i.cliente.numero_documento, i.cliente.telefono, i.alumno, i.plan.nombre, float(i.precio),
                        i.inicio, i.get_estado_display(), float(deuda.get(i.pk, {}).get("t") or 0), float(deuda.get(i.pk, {}).get("v") or 0)]
                       for i in qs[:20000]])
    pagina = Paginator(qs, 40).get_page(request.GET.get("page"))
    for i in pagina.object_list:
        d = deuda.get(i.pk, {})
        i.debe, i.vencido = d.get("t") or CERO, d.get("v") or CERO
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "cobranzas/inscritos.html", {
        "pagina": pagina, "query": query, "f": {"q": q, "plan": plan, "estado": estado},
        "planes": Plan.objects.all(),
        "estados": [("ACT", "Activos"), ("TER", "Terminados"), ("BAJ", "De baja"), ("todos", "Todos")],
    })


@permiso_requerido("cobranzas.inscribir")
def nueva_inscripcion(request):
    planes = Plan.objects.filter(activo=True)
    if not planes.exists():
        messages.warning(request, "Primero crea un plan.")
        return redirect("cobranzas:planes" if puede(request.user, "cobranzas.gestionar") else "cobranzas:inicio")
    inicial = {}
    cliente = None
    if request.GET.get("cliente", "").isdigit():
        cliente = Cliente.objects.filter(pk=request.GET["cliente"]).first()
        if cliente:
            inicial = {"cliente_id": cliente.pk, "nombre": cliente.nombre, "documento": cliente.numero_documento, "telefono": cliente.telefono}
    f = InscripcionForm(request.POST or None, initial=inicial)
    if request.method == "POST" and f.is_valid():
        d = f.cleaned_data
        try:
            cli = resolver_cliente(d["cliente_id"], d["nombre"], d["documento"])
            if cli and d["telefono"] and not cli.telefono:
                cli.telefono = d["telefono"]
                cli.save(update_fields=["telefono"])
            insc = inscribir(cli, d["plan"], request.user, d["inicio"], d["precio"], d["dia_pago"], d["alumno"], d["nota"],
                             d["cobrar_matricula"])
            messages.success(request, f"{insc.quien} inscrito en {insc.plan.nombre}." + (" Ya puedes cobrarle." if puede(request.user, "cobranzas.cobrar") else ""))
            return redirect("cobranzas:cuenta", pk=cli.pk)
        except (ClienteError, CobranzaError) as e:
            f.add_error(None, str(e))
    return render(request, "cobranzas/inscribir.html", {"form": f, "planes": planes, "cliente": cliente, "breadcrumb": _bc()})


@permiso_requerido("cobranzas.inscribir")
def editar_inscripcion(request, pk):
    insc = get_object_or_404(Inscripcion.objects.select_related("cliente", "plan"), pk=pk)
    precio_antes = insc.precio
    f = EditarInscripcionForm(request.POST or None, instance=insc)
    if request.method == "POST" and f.is_valid():
        insc = f.save(commit=False)
        insc.precio = precio_antes
        insc.save()
        if f.cleaned_data["precio"] != precio_antes:
            n = cambiar_precio(insc, f.cleaned_data["precio"])
            messages.info(request, f"Precio nuevo: S/ {insc.precio:.2f}" + (f" ({n} cuota{'s' if n != 1 else ''} pendiente{'s' if n != 1 else ''} actualizada{'s' if n != 1 else ''})." if n else "."))
        messages.success(request, "Inscripción guardada.")
        return redirect("cobranzas:cuenta", pk=insc.cliente_id)
    return render(request, "core/form.html", {
        "form": f, "titulo": f"{insc.quien} · {insc.plan.nombre}", "cancelar": reverse("cobranzas:cuenta", args=[insc.cliente_id]),
        "breadcrumb": _bc() + [(insc.cliente.nombre, reverse("cobranzas:cuenta", args=[insc.cliente_id]))],
        "ayuda": "El precio nuevo se aplica a las cuotas que aún no vencen ni tienen pagos, y a las que vengan. El día de pago, a las cuotas que se generen desde ahora."})


@permiso_requerido("cobranzas.inscribir")
@require_POST
def accion_inscripcion(request, pk, accion):
    insc = get_object_or_404(Inscripcion, pk=pk)
    try:
        if accion == "baja":
            n = dar_baja(insc, request.user, request.POST.get("motivo"))
            messages.success(request, f"{insc.quien} quedó de baja." + (f" Se quitaron {n} cuota{'s' if n != 1 else ''} que aún no vencían." if n else ""))
        elif accion == "reactivar":
            reactivar(insc)
            messages.success(request, f"{insc.quien} vuelve a estar activo.")
        elif accion == "adelantar":
            n = adelantar(insc, request.POST.get("n") or 1)
            messages.success(request, f"Se agregaron {n} periodo{'s' if n != 1 else ''} para pagar por adelantado.")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=insc.cliente_id)


@permiso_requerido("cobranzas.gestionar")
@require_POST
def accion_cuota(request, pk, accion):
    cuota = get_object_or_404(Cuota.objects.select_related("inscripcion__plan"), pk=pk)
    try:
        if accion == "exonerar":
            exonerar(cuota, request.user, request.POST.get("motivo"))
            messages.success(request, f"{cuota.concepto} exonerada.")
        elif accion == "mora":
            quitar_mora(cuota)
            messages.success(request, f"Se quitó la mora de {cuota.concepto}.")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=cuota.inscripcion.cliente_id)


# --- Morosos y por vencer ------------------------------------------------------------

@permiso_requerido("cobranzas.ver")
def morosos(request):
    al_dia()
    hoy = timezone.localdate()
    ver = "proximos" if request.GET.get("ver") == "proximos" else "vencidos"
    plan = request.GET.get("plan", "")
    cuotas = por_vencer(hoy) if ver == "proximos" else vencidas(hoy)
    if plan.isdigit():
        cuotas = cuotas.filter(inscripcion__plan_id=plan)
    grupos = agrupar_por_cliente(cuotas, hoy)
    if request.GET.get("excel"):
        return _excel("Morosos" if ver == "vencidos" else "Por vencer",
                      ["Cliente", "Documento", "Celular", "Alumno o socio", "Cuotas", "Debe", "Días de atraso"],
                      [[g["cliente"].nombre, g["cliente"].numero_documento, g["cliente"].telefono, ", ".join(g["quienes"]),
                        ", ".join(c.concepto for c in g["cuotas"]), float(g["total"]), g["atraso"] if ver == "vencidos" else 0]
                       for g in grupos])
    for g in grupos:
        g["wa"] = enlace_whatsapp(g["cliente"], g["cuotas"], hoy)
    return render(request, "cobranzas/morosos.html", {
        "grupos": grupos, "ver": ver, "plan": plan, "planes": Plan.objects.all(),
        "total": sum((g["total"] for g in grupos), CERO), "cfg": Config.cargar(), "es_vencidos": ver == "vencidos", "hoy": hoy,
    })


# --- Planes y configuración ----------------------------------------------------------

@permiso_requerido("cobranzas.gestionar")
def planes(request):
    lista = Plan.objects.annotate(activos=Count("inscripciones", filter=Q(inscripciones__estado=Inscripcion.Estado.ACTIVA)))
    return render(request, "cobranzas/planes.html", {"planes": lista, "cfg": Config.cargar()})


@permiso_requerido("cobranzas.gestionar")
def plan_form(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    anterior = plan.precio if plan else None
    f = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and f.is_valid():
        from core.bitacora import anotar

        from .servicios import aplicar_precio_plan

        with transaction.atomic():
            p = f.save()
            if plan and f.cleaned_data.get("aplicar_inscritos") and p.precio != anterior:
                avisos = aplicar_precio_plan(p, anterior)
                anotar("cobranza.precio_plan", f"{p.nombre}: de S/ {anterior:.2f} a S/ {p.precio:.2f} para {len(avisos)} inscrito{'s' if len(avisos) != 1 else ''}",
                       objeto=p, usuario=request.user)
                return render(request, "cobranzas/plan_avisos.html", {"plan": p, "anterior": anterior, "avisos": avisos})
        messages.success(request, f"Plan «{p.nombre}» guardado." + (" Los inscritos conservan su precio." if plan and p.precio != anterior else ""))
        return redirect("cobranzas:planes")
    return render(request, "core/form.html", {
        "form": f, "titulo": f"Editar {plan.nombre}" if plan else "Nuevo plan", "cancelar": reverse("cobranzas:planes"),
        "breadcrumb": _bc() + [("Planes", reverse("cobranzas:planes"))],
        "ayuda": "Mensual sin número de cuotas = cobra cada mes hasta que se dé de baja (gimnasio). Trimestral, semestral o anual = "
                 "se paga por adelantado cada 3, 6 o 12 meses. Con número de cuotas = un curso con duración fija. Pago único = una "
                 "sola vez (un taller); con días de vigencia sirve de pase diario o paquete (10 clases en 30 días)."})


@permiso_requerido("cobranzas.gestionar")
def configurar(request):
    cfg = Config.cargar()
    f = ConfigForm(request.POST or None, instance=cfg)
    if request.method == "POST" and f.is_valid():
        f.save()
        messages.success(request, "Configuración de cobranzas guardada.")
        return redirect("cobranzas:planes")
    return render(request, "core/form.html", {
        "form": f, "titulo": "Configuración de cobranzas", "cancelar": reverse("cobranzas:planes"),
        "breadcrumb": _bc() + [("Planes", reverse("cobranzas:planes"))],
        "ayuda": "La mora es opcional: un monto fijo que se suma a cada cuota atrasada pasados los días de gracia. "
                 "Se puede quitar en cada cuota."})


# --- Reporte -------------------------------------------------------------------------

@permiso_requerido("cobranzas.gestionar", "reportes.ver")
def reporte(request):
    hoy = timezone.localdate()
    try:
        anio, mes = (int(x) for x in request.GET.get("mes", "").split("-"))
        desde = date(anio, mes, 1)
    except (ValueError, TypeError):
        desde = hoy.replace(day=1)
    hasta = date(desde.year + desde.month // 12, desde.month % 12 + 1, 1)
    pagos = Pago.objects.filter(anulado=False, **dias("fecha", desde, antes_de=hasta)).select_related("cliente", "usuario")
    from ventas.models import MetodoPago

    nombres = dict(MetodoPago.choices)
    por_metodo = [{"metodo": nombres.get(m["metodo"], m["metodo"]), "t": m["t"], "n": m["n"]}
                  for m in pagos.values("metodo").annotate(t=Sum("monto"), n=Count("id")).order_by("-t")]
    por_plan = list(PagoCuota.objects.filter(pago__in=pagos).values("cuota__inscripcion__plan__nombre")
                    .annotate(t=Sum("monto")).order_by("-t"))
    por_usuario = list(pagos.values("usuario__first_name", "usuario__last_name", "usuario__username").annotate(t=Sum("monto"), n=Count("id")).order_by("-t"))
    cuotas_mes = Cuota.objects.filter(vence__gte=desde, vence__lt=hasta, anulada=False)
    emitido = cuotas_mes.aggregate(m=Sum("monto"), mo=Sum("mora"), p=Sum("pagado"))
    total_mes = (emitido["m"] or CERO) + (emitido["mo"] or CERO)
    if request.GET.get("excel"):
        return _excel(f"Cobros {desde:%Y-%m}", ["Recibo", "Fecha", "Cliente", "Documento", "Cuotas", "Método", "Monto", "Cobró"],
                      [[p.numero, timezone.localtime(p.fecha).replace(tzinfo=None), p.cliente.nombre, p.cliente.numero_documento,
                        ", ".join(f"{d.cuota.concepto} ({d.cuota.inscripcion.quien})" for d in p.detalles.all()),
                        p.get_metodo_display(), float(p.monto), p.usuario.get_full_name() or p.usuario.username]
                       for p in pagos.prefetch_related("detalles__cuota__inscripcion__cliente")])
    return render(request, "cobranzas/reporte.html", {
        "desde": desde, "mes": f"{desde:%Y-%m}", "pagos": pagos[:300], "n_pagos": pagos.count(),
        "total": pagos.aggregate(t=Sum("monto"))["t"] or CERO, "por_metodo": por_metodo, "por_plan": por_plan, "por_usuario": por_usuario,
        "emitido": total_mes, "cobrado_emitido": emitido["p"] or CERO,
        "porcentaje": round((emitido["p"] or 0) * 100 / total_mes) if total_mes else None,
        "nuevos": Inscripcion.objects.filter(inicio__gte=desde, inicio__lt=hasta).count(),
        "bajas": Inscripcion.objects.filter(estado=Inscripcion.Estado.BAJA, fin__gte=desde, fin__lt=hasta).count(),
        "anulados": Pago.objects.filter(anulado=True, **dias("fecha", desde, antes_de=hasta)).select_related("cliente", "anulado_por"),
    })


# --- Gimnasios: control de ingreso, carné y congelar --------------------------------

def _ingreso_activo():
    from core.models import Ajustes

    return Ajustes.cargar().usa_ingreso


@permiso_requerido("cobranzas.ingreso")
def ingreso(request):
    """La puerta: se busca al socio (DNI, nombre, celular o el QR de su carné) y se ve si puede entrar."""
    if not _ingreso_activo():
        messages.info(request, "El control de ingreso se enciende en Datos del negocio → Funciones → Control de ingreso.")
        return redirect("cobranzas:inicio")
    al_dia()
    hoy = timezone.localdate()
    cfg = Config.cargar()
    q = request.GET.get("q", "").strip()
    encontrados = []
    if q:
        insc = por_codigo(q)
        if insc:
            encontrados = list(para_ingreso(Inscripcion.objects.filter(pk=insc.pk)))
        elif len(q) >= 2:
            qs = Inscripcion.objects.exclude(estado=Inscripcion.Estado.BAJA)
            for palabra in q.split():
                qs = qs.filter(Q(cliente__nombre__icontains=palabra) | Q(alumno__icontains=palabra)
                               | Q(cliente__numero_documento__startswith=palabra) | Q(cliente__telefono__icontains=palabra))
            encontrados = list(para_ingreso(qs.order_by("cliente__nombre", "alumno"))[:12])
        for i in encontrados:
            i.e = estado_ingreso(i, hoy, cfg)
    hoy_qs = Asistencia.objects.filter(**dias("fecha", hoy, hoy))
    return render(request, "cobranzas/ingreso.html", {
        "q": q, "encontrados": encontrados, "hoy": hoy, "n_hoy": hoy_qs.count(),
        "ultimos": hoy_qs.select_related("inscripcion__cliente", "inscripcion__plan", "usuario")[:15],
    })


@permiso_requerido("cobranzas.ingreso")
@require_POST
def ingreso_registrar(request, pk):
    if not _ingreso_activo():
        return redirect("cobranzas:inicio")
    insc = get_object_or_404(para_ingreso(Inscripcion.objects.all()), pk=pk)
    permitir = request.POST.get("permitir") == "1"
    if permitir and not puede(request.user, "cobranzas.cobrar"):
        messages.error(request, "Solo quien cobra puede dejar pasar a alguien que no está al día.")
        return redirect(reverse("cobranzas:ingreso") + f"?q={codigo_carne(insc)}")
    try:
        registrar_ingreso(insc, request.user, permitir, request.POST.get("nota"))
        messages.success(request, f"Bienvenido, {insc.quien}." + (" (Entró sin estar al día.)" if permitir else ""))
        return redirect("cobranzas:ingreso")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect(reverse("cobranzas:ingreso") + f"?q={codigo_carne(insc)}")


@permiso_requerido("cobranzas.ver")
def carne(request, pk):
    """El carné para imprimir o mostrar en el celular: nombre, plan y el QR para entrar."""
    from core.utils import qr_svg

    insc = get_object_or_404(Inscripcion.objects.select_related("cliente", "plan"), pk=pk)
    return render(request, "cobranzas/carne.html", {"i": insc, "qr": qr_svg(codigo_carne(insc), 170), "codigo": codigo_carne(insc)})


@permiso_requerido("cobranzas.inscribir")
@require_POST
def congelar_vista(request, pk):
    insc = get_object_or_404(Inscripcion.objects.select_related("plan", "cliente"), pk=pk)
    try:
        desde = date.fromisoformat(request.POST.get("desde", ""))
    except ValueError:
        desde = None
    try:
        c = congelar(insc, desde, request.POST.get("dias"), request.POST.get("motivo"), request.user)
        messages.success(request, f"{insc.quien}: congelado del {c.desde:%d/%m} al {c.hasta:%d/%m}. Su vencimiento se corrió {c.dias} día{'s' if c.dias != 1 else ''}.")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=insc.cliente_id)


@permiso_requerido("cobranzas.inscribir")
@require_POST
def descongelar_vista(request, pk):
    c = get_object_or_404(Congelamiento.objects.select_related("inscripcion__plan", "inscripcion__cliente"), pk=pk)
    cliente = c.inscripcion.cliente_id
    try:
        n = descongelar(c, request.user)
        messages.success(request, f"Volvió antes: se devolvieron {n} día{'s' if n != 1 else ''} a su vencimiento.")
    except CobranzaError as e:
        messages.error(request, str(e))
    return redirect("cobranzas:cuenta", pk=cliente)
