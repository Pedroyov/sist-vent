import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.permisos import modulo_activo, permiso_requerido, puede
from core.utils import entero

from personal.models import Persona
from personal.reportes import de_persona

from .forms import AusenciaForm, ConfigForm
from .models import Ausencia, Cita, Config, Horario
from .servicios import (CitaError, Dia, a_esa_hora, dia_corto, a_hora, agendar, atender, cancelar, cerrar_pasadas, confirmar, dia_texto, duracion_de,
                        enlace_cita, enlace_horarios, hora_texto, m, mensaje_horarios, mis_horarios, no_vino, profesionales,
                        proximos, rangos_texto, reabrir, resumen_dia, registrar_servicios, por_cobrar as lista_por_cobrar,
                        marcar_cobradas, contar_por_cobrar, clave_cuenta, de_la_cuenta, editar_cuenta, quitar_de_cuenta, se_puede_quitar, SIN_NOMBRE,
                        empezar, terminar, en_atencion_ahora)

VER = ("citas.ver", "citas.gestionar")
PPM = 1.4  # alto de la agenda: píxeles por minuto


def _mio(user):
    """El profesional de este usuario (si atiende y tiene el permiso de su agenda)."""
    if not puede(user, "citas.mi_agenda", "citas.agendar_propias"):
        return None
    return Persona.objects.filter(usuario=user, activo=True, atiende_citas=True).first()


def _puede_cita(user, c, accion):
    """gestionar = todo; el profesional, con lo suyo: atender / no vino siempre; el resto si agenda sus propias citas."""
    if puede(user, "citas.gestionar"):
        return True
    mio = _mio(user)
    if mio is None or c.profesional_id != mio.pk:
        return False
    if accion in ("atender", "no_vino", "ver", "empezar", "terminar"):
        return True
    return puede(user, "citas.agendar_propias")


def _servicios():
    from productos.models import Producto, Variante

    return list(Variante.objects.filter(activa=True, producto__activo=True, producto__tipo=Producto.Tipo.SERVICIO)
                .select_related("producto").order_by("producto__nombre", "orden", "nombre"))


def _destino(request, c=None):
    sig = request.POST.get("next") or request.GET.get("next")
    if sig and url_has_allowed_host_and_scheme(sig, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return sig
    if c is not None:
        return reverse("citas:detalle", args=[c.pk])
    return reverse("citas:agenda")


# --- Agenda del día ------------------------------------------------------------------------

@permiso_requerido(*VER, "citas.mi_agenda")
def agenda(request):
    if not puede(request.user, *VER):
        return redirect("citas:mi_agenda")
    cerrar_pasadas()
    hoy = timezone.localdate()
    fecha = parse_date(request.GET.get("fecha") or "") or hoy
    cfg = Config.cargar()
    dia = Dia(fecha)
    personal = list(Persona.objects.filter(activo=True, atiende_citas=True).prefetch_related("horarios"))
    citas = list(Cita.objects.filter(fecha=fecha).select_related("profesional", "servicio__producto").order_by("inicio"))
    if request.GET.get("excel"):
        from core.excel import descargar

        return descargar(f"citas_{fecha:%Y%m%d}", [(f"Citas {fecha:%d.%m.%Y}", ["Inicio", "Fin", "Cliente", "Celular", "Servicio", "Atiende",
                                                                             "Precio", "Estado", "Cobrada"],
                                                    [[c.inicio.strftime("%H:%M"), c.fin.strftime("%H:%M"), c.nombre, c.telefono, c.servicio_nombre,
                                                      c.profesional.nombre, c.precio if c.precio is not None else "", c.get_estado_display(),
                                                      "Sí" if c.cobrada else "No"] for c in citas])])
    # alto de la agenda: de la primera entrada a la última salida (o 9 a 19 si nadie trabaja)
    inicios = [m(h.entrada) for h in dia.horarios.values()] + [m(c.inicio) for c in citas]
    fines = [m(h.salida) for h in dia.horarios.values()] + [m(c.fin) for c in citas]
    desde = (min(inicios) // 60) * 60 if inicios else 9 * 60
    hasta = -(-max(fines) // 60) * 60 if fines else 19 * 60
    alto = (hasta - desde) * PPM
    gestiona = puede(request.user, "citas.gestionar")
    columnas = []
    for p in personal:
        suyas = [c for c in citas if c.profesional_id == p.pk]
        jornada = dia.jornada(p)
        if not jornada and not suyas and fecha.weekday() not in {h.dia for h in p.horarios.all()} and not dia.ausencia(p):
            continue  # no trabaja ese día de la semana
        h = dia.horarios.get(p.pk)
        bloques = []
        for c in suyas:
            if c.estado == Cita.Estado.CANCELADA:
                continue
            minutos = c.minutos
            if c.en_atencion and fecha == hoy:  # se pasó del tiempo: el bloque crece hasta ahora
                ahora_min = timezone.localtime().hour * 60 + timezone.localtime().minute
                minutos = max(minutos, ahora_min - m(c.inicio))
            bloques.append({"c": c, "top": (m(c.inicio) - desde) * PPM, "alto": max(minutos * PPM, 22)})
        trabaja = [{"top": (a - desde) * PPM, "alto": (b - a) * PPM} for a, b in jornada]
        huecos = []
        if gestiona:
            for a, b in dia.libres(p):
                t = -(-a // 30) * 30
                while t + 15 <= b:
                    huecos.append({"top": (t - desde) * PPM, "alto": min(30, b - t) * PPM, "hora": a_hora(t)})
                    t += 30
        aus = dia.ausencia(p)
        columnas.append({"p": p, "bloques": bloques, "trabaja": trabaja, "huecos": huecos, "horario": h,
                         "ausencia": aus, "n": sum(1 for c in suyas if c.estado != Cita.Estado.CANCELADA)})
    ahora = timezone.localtime()
    linea = (ahora.hour * 60 + ahora.minute - desde) * PPM if fecha == hoy and desde <= ahora.hour * 60 + ahora.minute <= hasta else None
    return render(request, "citas/agenda.html", {
        "fecha": fecha, "hoy": hoy, "manana": hoy + timedelta(days=1), "anterior": fecha - timedelta(days=1),
        "siguiente": fecha + timedelta(days=1), "columnas": columnas, "alto": alto, "linea": linea,
        "horas": [{"top": (t - desde) * PPM, "h": a_hora(t)} for t in range(desde, hasta, 60)],
        "r": resumen_dia(fecha), "hay_personal": bool(personal), "cfg": cfg,
        "lista": [c for c in citas], "gestiona": gestiona,
        "n_por_cobrar": contar_por_cobrar() if puede(request.user, "ventas.vender", "citas.gestionar") else 0,
        "en_atencion": en_atencion_ahora() if fecha == hoy else [], "cobrar": _puede_cobrar(request.user),
    })


# --- Una cita ------------------------------------------------------------------------------

def _cita(request, pk, accion="ver"):
    c = get_object_or_404(Cita.objects.select_related("profesional", "servicio__producto", "cliente", "creada_por"), pk=pk)
    if not (puede(request.user, *VER) or _puede_cita(request.user, c, accion)):
        raise PermissionDenied
    return c


@permiso_requerido(*VER, "citas.mi_agenda")
def detalle(request, pk):
    c = _cita(request, pk)
    return render(request, "citas/detalle.html", {
        "c": c, "hoy": timezone.localdate(), "wa": enlace_cita(c) if c.activa else "",
        "p_atender": _puede_cita(request.user, c, "atender"), "p_editar": _puede_cita(request.user, c, "editar"),
        "cobrar": c.servicio_id and modulo_activo(request.user, "mostrador") and puede(request.user, "ventas.vender"),
        "otras": Cita.objects.filter(telefono=c.telefono).exclude(pk=c.pk).select_related("profesional").order_by("-fecha", "-inicio")[:6]
        if c.telefono else [],
    })


ACCIONES = {"confirmar": confirmar, "cancelar": cancelar, "no_vino": no_vino, "reabrir": reabrir, "atender": atender,
            "empezar": empezar, "terminar": terminar}


def _puede_cobrar(user):
    return modulo_activo(user, "mostrador") and puede(user, "ventas.vender")


@require_POST
@permiso_requerido(*VER, "citas.mi_agenda")
def accion(request, pk, accion):
    if accion not in ACCIONES:
        raise Http404
    c = _cita(request, pk, accion)
    if not _puede_cita(request.user, c, accion):
        raise PermissionDenied
    try:
        hecho = ACCIONES[accion](c, request.user)
    except CitaError as e:
        messages.error(request, str(e))
        return redirect(_destino(request, c))
    if accion == "terminar":  # toda la atención (la cita y lo «algo más»), con la hora real
        ids = ",".join(str(x.pk) for x in hecho)
        messages.success(request, f"Terminó {', '.join(x.servicio_nombre or 'el servicio' for x in hecho)} de {c.nombre}: "
                                  "ya está en «Por cobrar».")
        if request.POST.get("cobrar") and _puede_cobrar(request.user):
            return redirect(f"{reverse('ventas:pos')}?citas={ids}")
        return redirect(_destino(request, c))
    textos = {"confirmar": "confirmada", "cancelar": "cancelada", "no_vino": "marcada como «No vino»", "reabrir": "activa otra vez",
              "atender": "atendida", "empezar": "en atención: toca «Terminar» cuando acabe"}
    messages.success(request, f"Cita de {c.nombre} {textos[accion]}.")
    if accion == "atender" and request.POST.get("cobrar") and c.servicio_id and _puede_cobrar(request.user):
        return redirect(f"{reverse('ventas:pos')}?citas={c.pk}")
    return redirect(_destino(request, c))


# --- Agendar -------------------------------------------------------------------------------

@permiso_requerido("citas.gestionar", "citas.agendar_propias")
def formulario(request, pk=None):
    gestiona = puede(request.user, "citas.gestionar")
    mio = None if gestiona else _mio(request.user)
    if not gestiona and mio is None:
        messages.error(request, "Tu usuario no está enlazado a un profesional. Pídelo al administrador.")
        return redirect("core:inicio")
    c = None
    if pk:
        c = _cita(request, pk, "editar")
        if not _puede_cita(request.user, c, "editar"):
            raise PermissionDenied
        if not c.activa:
            messages.warning(request, f"Esta cita ya está como «{c.get_estado_display()}»: no se puede cambiar.")
            return redirect("citas:detalle", pk=c.pk)
    servicios = _servicios()
    cfg = Config.cargar()
    personal = [mio] if mio else list(Persona.objects.filter(activo=True, atiende_citas=True).prefetch_related("servicios"))
    error = None
    if request.method == "POST":
        d = request.POST
        datos = {k: d.get(k, "") for k in ("servicio", "duracion", "profesional", "fecha", "hora", "telefono", "nombre", "nota")}
        serv = next((v for v in servicios if str(v.pk) == datos["servicio"]), None)
        prof = mio or next((p for p in personal if str(p.pk) == datos["profesional"]), None)
        try:
            c2 = agendar(request.user, c, profesional=prof, fecha=parse_date(datos["fecha"] or ""), inicio=parse_time(datos["hora"] or ""),
                         duracion=entero(datos["duracion"]) or duracion_de(serv, cfg), servicio=serv, nombre=datos["nombre"],
                         telefono=datos["telefono"], nota=datos["nota"], forzar=gestiona and bool(d.get("forzar")))
        except (CitaError, ValueError) as e:
            error = str(e)
        else:
            messages.success(request, f"Cita {'guardada' if c else 'agendada'}: {c2.nombre} con {c2.profesional.nombre}, "
                                      f"{dia_texto(c2.fecha)} a las {hora_texto(c2.inicio)}.")
            return redirect(reverse("citas:detalle", args=[c2.pk]) + "?nueva=1")
    elif c is not None:
        datos = {"servicio": str(c.servicio_id or ""), "duracion": str(c.minutos), "profesional": str(c.profesional_id),
                 "fecha": c.fecha.isoformat(), "hora": c.inicio.strftime("%H:%M"), "telefono": c.telefono, "nombre": c.nombre, "nota": c.nota}
    else:
        g = request.GET
        fecha = parse_date(g.get("fecha") or "") or timezone.localdate()
        datos = {"servicio": g.get("servicio", ""), "duracion": "", "profesional": str(mio.pk) if mio else g.get("profesional", ""),
                 "fecha": max(fecha, timezone.localdate()).isoformat(), "hora": g.get("hora", ""), "telefono": "", "nombre": "", "nota": ""}
    return render(request, "citas/form.html", {
        "c": c, "datos": datos, "servicios": servicios, "personal": personal, "mio": mio, "error": error, "gestiona": gestiona,
        "duraciones": json.dumps({str(v.pk): duracion_de(v, cfg) for v in servicios}),
        "hacen": json.dumps({str(p.pk): [s.pk for s in p.servicios.all()] for p in personal}),
        "producto_de": json.dumps({str(v.pk): v.producto_id for v in servicios}), "cfg": cfg,
    })


@permiso_requerido("citas.gestionar", "citas.agendar_propias")
def horarios(request):
    """Panel del formulario: horarios libres, y si está ocupado, la próxima hora con esa persona o quién atiende a esa hora."""
    g = request.GET
    cfg = Config.cargar()
    mio = None if puede(request.user, "citas.gestionar") else _mio(request.user)
    from productos.models import Variante

    serv = Variante.objects.select_related("producto").filter(pk=entero(g.get("servicio"))).first() if g.get("servicio") else None
    duracion = entero(g.get("duracion")) or duracion_de(serv, cfg)
    duracion = max(5, min(duracion, 600))
    fecha = parse_date(g.get("fecha") or "") or timezone.localdate()
    hora = parse_time(g.get("hora") or "")
    excluir = Cita.objects.filter(pk=entero(g.get("excluir"))).first() if g.get("excluir") else None
    dia = Dia(fecha, excluir)
    prof = mio or (Persona.objects.filter(pk=entero(g.get("profesional")), activo=True, atiende_citas=True).first() if g.get("profesional") else None)
    ctx = {"fecha": fecha, "duracion": duracion, "hora": hora, "prof": prof, "hoy": timezone.localdate(), "dia_txt": dia_texto(fecha)}
    if prof is not None:
        libres = dia.horarios_libres(prof, duracion, cfg.intervalo)
        ctx["libres"] = [a_hora(t) for t in libres]
        ctx["ausencia"] = dia.ausencia(prof)
        ctx["no_hace"] = serv is not None and not prof.hace(serv.producto_id)
        ocupada = hora is not None and m(hora) not in libres
        ctx["ocupada"] = ocupada
        if ocupada or not libres:
            # si ese día tiene otros horarios ya se ven arriba: los próximos empiezan al día siguiente
            desde = fecha + timedelta(days=1) if libres else fecha
            desde_min = m(hora) if hora and not libres else 0
            ctx["proximos"] = [(f, a_hora(t), dia_corto(f)) for f, t in
                               proximos(prof, duracion, desde, desde_min, n=6, cfg=cfg, excluir=excluir)]
            if not mio:
                ctx["otros"] = [(p, a_hora(t)) for p, t in a_esa_hora(fecha, m(hora) if hora else (libres[0] if libres else 9 * 60),
                                                                      duracion, serv, sin=prof, cfg=cfg, excluir=excluir)]
    else:
        ctx["todos"] = [(p, [a_hora(t) for t in dia.horarios_libres(p, duracion, cfg.intervalo)][:16], dia.ausencia(p))
                        for p in profesionales(serv)]
    return render(request, "citas/partials/horarios.html", ctx)


# --- Mi agenda (quien atiende) -------------------------------------------------------------

@permiso_requerido("citas.mi_agenda", "citas.agendar_propias")
def mi_agenda(request):
    mio = _mio(request.user)
    if mio is None:
        return render(request, "citas/mi_agenda.html", {"sin_profesional": True})
    cerrar_pasadas()
    hoy = timezone.localdate()
    citas = list(Cita.objects.filter(profesional=mio, fecha__gte=hoy, fecha__lte=hoy + timedelta(days=13))
                 .exclude(estado=Cita.Estado.CANCELADA).select_related("servicio__producto").order_by("fecha", "inicio"))
    por_dia = {}
    for c in citas:
        por_dia.setdefault(c.fecha, []).append(c)
    cfg = Config.cargar()
    return render(request, "citas/mi_agenda.html", {
        "mio": mio, "hoy": hoy, "dias": [(f, dia_corto(f), lista) for f, lista in por_dia.items()],
        "libres": [(f, dia_corto(f), rangos_texto(rangos)) for f, rangos in mis_horarios(mio, cfg=cfg)], "wa": enlace_horarios(mio, cfg),
        "texto": mensaje_horarios(mio, cfg=cfg), "r": resumen_dia(hoy, mio), "puede_agendar": puede(request.user, "citas.agendar_propias"),
        "horario": list(mio.horarios.all()), "ausencias": mio.ausencias.filter(hasta__gte=hoy)[:5],
        "mes": de_persona(mio, hoy.replace(day=1), hoy), "en_atencion": en_atencion_ahora(mio), "cobrar": _puede_cobrar(request.user),
    })


# --- Personal ------------------------------------------------------------------------------

def horarios_de(p):
    """Para la ficha de la persona (personal/ficha.html): su semana y sus ausencias recientes."""
    hoy = timezone.localdate()
    actuales = {h.dia: h for h in p.horarios.all()} if p else {}
    inicial = []
    for d in range(7):
        h = actuales.get(d)
        if h:
            inicial.append({"trabaja": True, "entrada": h.entrada, "salida": h.salida, "descanso_desde": h.descanso_desde,
                            "descanso_hasta": h.descanso_hasta})
        else:
            inicial.append({"trabaja": p is None and d < 6, "entrada": "09:00", "salida": "19:00" if d < 5 else "14:00",
                            "descanso_desde": "13:00" if d < 5 else None, "descanso_hasta": "14:00" if d < 5 else None})
    return inicial


def guardar_horarios(p, dias):
    for d, f in enumerate(dias.forms):
        x = f.cleaned_data
        if x.get("trabaja"):
            Horario.objects.update_or_create(profesional=p, dia=d, defaults={
                "entrada": x["entrada"], "salida": x["salida"], "descanso_desde": x.get("descanso_desde"),
                "descanso_hasta": x.get("descanso_hasta")})
        else:
            Horario.objects.filter(profesional=p, dia=d).delete()


@require_POST
@permiso_requerido("personal.editar")
def ausencia(request, pk):
    p = get_object_or_404(Persona, pk=pk)
    form = AusenciaForm(request.POST)
    if form.is_valid():
        a = form.save(commit=False)
        a.profesional = p
        a.save()
        afectadas = Cita.objects.filter(profesional=p, fecha__gte=a.desde, fecha__lte=a.hasta, estado__in=Cita.ACTIVAS)
        if not a.todo_el_dia:
            afectadas = [c for c in afectadas if m(c.inicio) < m(a.hora_hasta) and m(c.fin) > m(a.hora_desde)]
        n = len(list(afectadas))
        messages.success(request, f"Ausencia de {p.nombre} guardada.")
        if n:
            messages.warning(request, f"Ojo: {p.nombre} tiene {n} cita{'s' if n != 1 else ''} en esas fechas. Cámbialas de hora o de persona en la agenda.")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("personal:persona", args=[p.pk]) + "#ausencias")


@require_POST
@permiso_requerido("personal.editar")
def ausencia_borrar(request, pk):
    a = get_object_or_404(Ausencia, pk=pk)
    a.delete()
    messages.success(request, "Ausencia quitada.")
    return redirect(reverse("personal:persona", args=[a.profesional_id]) + "#ausencias")


@require_POST
@permiso_requerido("personal.editar")
def configurar(request):
    form = ConfigForm(request.POST, instance=Config.cargar())
    if form.is_valid():
        form.save()
        messages.success(request, "Configuración de citas guardada.")
    else:
        messages.error(request, "Revisa la configuración.")
    return redirect("personal:lista")


# --- Servicios hechos: el trabajador avisa y caja cobra --------------------------------------

@permiso_requerido("citas.gestionar", "citas.mi_agenda")
def registrar(request):
    """Cliente sin cita (o algo más en una cita): quien atendió marca los servicios y quedan «por cobrar» en caja."""
    gestiona = puede(request.user, "citas.gestionar")
    mio = _mio(request.user)
    if not gestiona and mio is None:
        messages.error(request, "Tu usuario no está enlazado a un profesional. Pídelo al administrador.")
        return redirect("core:inicio")
    cita = None
    if request.GET.get("cita") or request.POST.get("cita"):
        cita = _cita(request, entero(request.GET.get("cita") or request.POST.get("cita")), "atender")
        if not _puede_cita(request.user, cita, "atender"):
            raise PermissionDenied
    personal = list(Persona.objects.filter(activo=True, atiende_citas=True).prefetch_related("servicios")) if gestiona else [mio]
    servicios = _servicios()
    error = None
    if request.method == "POST":
        d = request.POST
        prof = next((p for p in personal if str(p.pk) == d.get("profesional")), None) if gestiona else mio
        elegidos = []
        for v in servicios:  # cada servicio marcado, tantas veces como se indicó
            elegidos += [v] * max(0, min(entero(d.get(f"s{v.pk}")) or 0, 10))
        ahora = cita is None and d.get("momento", "ahora") == "ahora"
        try:
            hechos = registrar_servicios(request.user, prof, elegidos, d.get("nombre", ""), d.get("telefono", ""), d.get("nota", ""), cita,
                                         empezar=ahora, empezo_hace=entero(d.get("hace")) or None)
        except CitaError as e:
            error = str(e)
        else:
            total = sum(c.servicio.precio_venta for c in hechos)
            servicios_txt = f"{', '.join(c.servicio_nombre for c in hechos)} de {hechos[0].nombre} (S/ {total:.2f})"
            if hechos[0].en_atencion:
                messages.success(request, f"En atención: {servicios_txt}. Toca «Terminar» cuando acabe y pasa a caja.")
            else:
                messages.success(request, f"Listo: {servicios_txt}. Caja ya lo ve en «Por cobrar».")
            if cita is not None:
                return redirect(_destino(request, cita))  # «Agregar servicio» desde Por cobrar vuelve a la tarjeta
            return redirect("citas:agenda" if gestiona and not mio else "citas:mi_agenda")
    return render(request, "citas/registrar.html", {
        "cita": cita, "personal": personal, "mio": mio, "gestiona": gestiona, "servicios": servicios, "error": error,
        "hacen": {str(p.pk): [s.pk for s in p.servicios.all()] for p in personal + ([cita.profesional] if cita else [])},
        "hace_opciones": [("", "Según el servicio"), ("15", "Hace 15 min"), ("30", "30 min"), ("45", "45 min"), ("60", "1 h"), ("90", "1 h 30")],
        "datos": request.POST if request.method == "POST" else {"profesional": str(cita.profesional_id if cita else (mio.pk if mio else ""))},
    })


@permiso_requerido("ventas.vender", "citas.gestionar")
def por_cobrar(request):
    return render(request, "citas/por_cobrar.html", {"grupos": lista_por_cobrar(), "hoy": timezone.localdate(),
                                                     "vender": _puede_cobrar(request.user), "cobrar": _puede_cobrar(request.user),
                                                     "en_atencion": en_atencion_ahora()})


@permiso_requerido("ventas.vender", "citas.gestionar")
def cuenta(request, cuenta):
    """Una tarjeta de «Por cobrar»: ponerle nombre y celular (si el cliente no se registró al llegar), quitar o agregar servicios."""
    citas = de_la_cuenta(cuenta)
    if not citas:
        messages.info(request, "Esa cuenta ya se cobró o ya no está por cobrar.")
        return redirect("citas:por_cobrar")
    error = None
    if request.method == "POST":
        try:
            editar_cuenta(cuenta, request.user, request.POST.get("nombre", ""), request.POST.get("telefono", ""))
        except CitaError as e:
            error = str(e)
        else:
            messages.success(request, "Cuenta actualizada.")
            return redirect("citas:por_cobrar")
    for c in citas:
        c.quitable = se_puede_quitar(c)
    sin_nombre = citas[0].nombre == SIN_NOMBRE
    return render(request, "citas/cuenta.html", {
        "cuenta": cuenta, "citas": citas, "error": error, "total": sum((c.servicio.precio_venta for c in citas if c.servicio_id), 0),
        "datos": request.POST if request.method == "POST" else {"nombre": "" if sin_nombre else citas[0].nombre, "telefono": citas[0].telefono},
        "agregar": puede(request.user, "citas.gestionar"), "ultima": citas[-1],
    })


@require_POST
@permiso_requerido("ventas.vender", "citas.gestionar")
def cuenta_quitar(request, pk):
    c = get_object_or_404(Cita, pk=pk)
    cuenta = clave_cuenta(c)
    try:
        quitar_de_cuenta(c, request.user)
    except CitaError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Se quitó {c.servicio_nombre}.")
    return redirect("citas:cuenta", cuenta=cuenta)


@require_POST
@permiso_requerido("ventas.vender", "citas.gestionar")
def cobrada_aparte(request):
    ids = [entero(x) for x in request.POST.get("ids", "").split(",") if entero(x)]
    n = marcar_cobradas(ids)
    messages.success(request, f"{n} servicio{'s' if n != 1 else ''} marcado{'s' if n != 1 else ''} como ya cobrado{'s' if n != 1 else ''}.")
    return redirect("citas:por_cobrar")
