"""Inscribir, generar cuotas, cobrar, anular, dar de baja. Las reglas de cobranza están todas aquí."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from core.utils import dias, enlace_whatsapp as _enlace_wa

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.utils import timezone

from .models import CERO, Asistencia, Config, Congelamiento, Cuota, Inscripcion, Pago, PagoCuota, Plan

MESES = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "set.", "oct.", "nov.", "dic."]
POR_BAJA = "Por baja"
_DEC = DecimalField(max_digits=12, decimal_places=2)
PENDIENTE = ExpressionWrapper(F("monto") + F("mora") - F("pagado"), output_field=_DEC)


class CobranzaError(Exception):
    pass


def modulo_activo():
    from core.permisos import modulos_activos

    return "cobranzas" in modulos_activos()


def _monto(valor, minimo=Decimal("0.01")):
    try:
        m = Decimal(str(valor).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise CobranzaError("Monto no válido.")
    if m < minimo:
        raise CobranzaError("El monto debe ser mayor que cero." if minimo else "El monto no puede ser negativo.")
    return m


# --- Fechas y nombres de las cuotas ------------------------------------------------

def sumar_meses(fecha, meses, dia):
    total = fecha.month - 1 + meses
    anio, mes = fecha.year + total // 12, total % 12 + 1
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


MESES_POR = {Plan.Frecuencia.MENSUAL: 1, Plan.Frecuencia.TRIMESTRAL: 3, Plan.Frecuencia.SEMESTRAL: 6, Plan.Frecuencia.ANUAL: 12}
NOMBRE_PERIODO = {Plan.Frecuencia.TRIMESTRAL: "Trimestre", Plan.Frecuencia.SEMESTRAL: "Semestre", Plan.Frecuencia.ANUAL: "Año"}


def siguiente_vence(insc, vence):
    """Cuándo vence la cuota que sigue a la que vence en `vence`: cada periodo cuenta desde el anterior, así que al
    congelar basta con correr las cuotas que vienen."""
    f = insc.plan.frecuencia
    if f == Plan.Frecuencia.SEMANAL:
        return vence + timedelta(days=7)
    if f == Plan.Frecuencia.QUINCENAL:
        return vence + timedelta(days=15)
    return sumar_meses(vence, MESES_POR.get(f, 1), insc.dia_pago)  # por meses: vence en su día de pago


def vence_cuota(insc, k):
    """Fecha en que vence la cuota k (1, 2, 3…), contando desde el inicio. La primera vence el día que empieza."""
    vence = insc.inicio
    if insc.plan.frecuencia != Plan.Frecuencia.UNICO:
        for _ in range(max(0, k - 1)):
            vence = siguiente_vence(insc, vence)
    return vence


def concepto_cuota(insc, k, vence):
    plan = insc.plan
    if plan.frecuencia == Plan.Frecuencia.UNICO:
        return plan.nombre[:80]
    if plan.num_cuotas:
        return f"Cuota {k} de {plan.num_cuotas}"
    if plan.frecuencia == Plan.Frecuencia.MENSUAL:
        return f"Mensualidad {MESES[vence.month - 1]} {vence.year}"
    if plan.frecuencia in NOMBRE_PERIODO:
        return f"{NOMBRE_PERIODO[plan.frecuencia]} desde {MESES[vence.month - 1]} {vence.year}"
    return f"{'Semana' if plan.frecuencia == Plan.Frecuencia.SEMANAL else 'Quincena'} del {vence:%d/%m}"


def total_cuotas(plan):
    """Cuántas cuotas tiene el plan en total (None = sin fin)."""
    if plan.frecuencia == Plan.Frecuencia.UNICO:
        return 1
    return plan.num_cuotas or None


def generar(insc, hoy=None, extra=0):
    """Crea las cuotas que faltan: todas si el plan tiene un número fijo; si no tiene fin, las que ya vencieron o
    vencen pronto (según los días de aviso) y `extra` más para pagar por adelantado. Devuelve cuántas creó."""
    if insc.estado == Inscripcion.Estado.BAJA:
        return 0
    hoy = hoy or timezone.localdate()
    hasta = hoy + timedelta(days=Config.cargar().dias_aviso)
    previa = insc.cuotas.filter(numero__gt=0).order_by("-numero").first()
    ultima, vence = (previa.numero, previa.vence) if previa else (0, None)
    tope = total_cuotas(insc.plan)
    nuevas = []
    k = ultima + 1
    while tope is None or k <= tope:
        vence = insc.inicio if vence is None or insc.plan.frecuencia == Plan.Frecuencia.UNICO else siguiente_vence(insc, vence)
        if tope is None and k > 1 and vence > hasta and extra <= 0:
            break
        if tope is None and k > 1 and vence > hasta:
            extra -= 1
        nuevas.append(Cuota(inscripcion=insc, numero=k, concepto=concepto_cuota(insc, k, vence), vence=vence, monto=insc.precio))
        k += 1
        if len(nuevas) > 400:  # por si acaso (una inscripción semanal muy antigua)
            break
    if nuevas:
        Cuota.objects.bulk_create(nuevas, ignore_conflicts=True)
    return len(nuevas)


def al_dia(hoy=None):
    """Lo que el sistema hace solo, cada vez que alguien mira la cobranza: genera las cuotas nuevas de los planes
    sin fin y, si está activada, pone la mora a las cuotas atrasadas. No necesita tareas programadas."""
    hoy = hoy or timezone.localdate()
    cfg = Config.cargar()
    hasta = hoy + timedelta(days=cfg.dias_aviso)
    pendientes = (Inscripcion.objects.filter(estado=Inscripcion.Estado.ACTIVA, plan__num_cuotas=0)
                  .exclude(plan__frecuencia=Plan.Frecuencia.UNICO).select_related("plan")
                  .annotate(ultima=Max("cuotas__vence", filter=Q(cuotas__numero__gt=0))))
    for insc in pendientes.filter(Q(ultima__isnull=True) | Q(ultima__lt=hasta)):
        generar(insc, hoy)
    # pases y paquetes con días de vigencia: terminan solos cuando se acaban sus días
    for insc in (Inscripcion.objects.filter(estado=Inscripcion.Estado.ACTIVA, plan__frecuencia=Plan.Frecuencia.UNICO,
                                            plan__duracion_dias__gt=0, inicio__lt=hoy).select_related("plan")):
        if vigencia(insc, hoy)["hasta"] < hoy:
            _revisar_terminada(insc)
    if cfg.cobra_mora:
        limite = hoy - timedelta(days=cfg.dias_gracia)
        (Cuota.objects.filter(anulada=False, mora=0, mora_perdonada=False, numero__gt=0, vence__lt=limite,
                              pagado__lt=F("monto"))
         .update(mora=cfg.mora_monto))


# --- Inscribir, cambiar y dar de baja -----------------------------------------------

def inscribir(cliente, plan, usuario, inicio=None, precio=None, dia_pago=None, alumno="", nota="", cobrar_matricula=True):
    if not plan.activo:
        raise CobranzaError("Ese plan está desactivado.")
    if cliente is None:
        raise CobranzaError("Elige o escribe el cliente.")
    inicio = inicio or timezone.localdate()
    precio = plan.precio if precio in (None, "") else _monto(precio, CERO)
    alumno = " ".join(str(alumno or "").split())[:120]
    if alumno.lower() == cliente.nombre.lower():
        alumno = ""
    repetida = Inscripcion.objects.filter(cliente=cliente, plan=plan, alumno=alumno, estado=Inscripcion.Estado.ACTIVA).first()
    if repetida:
        raise CobranzaError(f"{repetida.quien} ya está inscrito en {plan.nombre}.")
    with transaction.atomic():
        insc = Inscripcion.objects.create(cliente=cliente, plan=plan, precio=precio, inicio=inicio,
                                          dia_pago=dia_pago or inicio.day, alumno=alumno, nota=str(nota or "")[:200], usuario=usuario)
        if plan.matricula and cobrar_matricula:
            Cuota.objects.create(inscripcion=insc, numero=0, concepto="Matrícula", vence=inicio, monto=plan.matricula)
        generar(insc)
    return insc


def cambiar_precio(insc, precio):
    """El precio nuevo vale para las cuotas que todavía no se pagaron nada y no han vencido, y para las que vengan."""
    precio = _monto(precio, CERO)
    with transaction.atomic():
        insc.precio = precio
        insc.save(update_fields=["precio"])
        n = (insc.cuotas.filter(numero__gt=0, pagado=0, anulada=False, vence__gte=timezone.localdate())
             .update(monto=precio))
    return n


def aplicar_precio_plan(plan, anterior, hoy=None):
    """El plan cambió de precio: lo cobran desde su próxima cuota sin pagar los inscritos (activos) que pagaban el precio
    del plan. Los que tienen precio especial o beca se quedan. Devuelve [{"insc", "desde", "wa"}] para avisarles."""
    hoy = hoy or timezone.localdate()
    salida = []
    for insc in (Inscripcion.objects.filter(plan=plan, estado=Inscripcion.Estado.ACTIVA, precio=anterior)
                 .select_related("cliente", "plan")):
        cambiar_precio(insc, plan.precio)
        proxima = insc.cuotas.filter(numero__gt=0, pagado=0, anulada=False, vence__gte=hoy).order_by("vence").first()
        desde = proxima.vence if proxima else None
        texto = (f"Hola {insc.cliente.nombre.split()[0]}, te avisamos que "
                 + (f"desde el {desde:%d/%m/%Y} " if desde else "desde tu próximo pago ")
                 + f"{insc.plan.nombre}" + (f" ({insc.alumno})" if insc.alumno else "")
                 + f" será S/ {plan.precio:.2f}. ¡Gracias por seguir con nosotros!")
        salida.append({"insc": insc, "desde": desde,
                       "wa": _enlace_wa(insc.cliente.telefono, texto) if insc.cliente.whatsapp else ""})
    return salida


def dar_baja(insc, usuario, motivo=""):
    if insc.estado == Inscripcion.Estado.BAJA:
        raise CobranzaError("Ya estaba de baja.")
    hoy = timezone.localdate()
    with transaction.atomic():
        insc.estado, insc.fin, insc.motivo_baja = Inscripcion.Estado.BAJA, hoy, " ".join(str(motivo or "").split())[:200]
        insc.save(update_fields=["estado", "fin", "motivo_baja"])
        # Las cuotas que aún no vencen y no se pagaron se quitan; lo vencido se sigue debiendo
        n = insc.cuotas.filter(vence__gt=hoy, pagado=0, anulada=False).update(anulada=True, nota=POR_BAJA)
    return n


def reactivar(insc):
    if insc.estado != Inscripcion.Estado.BAJA:
        raise CobranzaError("La inscripción no está de baja.")
    with transaction.atomic():
        insc.estado, insc.fin, insc.motivo_baja = Inscripcion.Estado.ACTIVA, None, ""
        insc.save(update_fields=["estado", "fin", "motivo_baja"])
        insc.cuotas.filter(anulada=True, nota=POR_BAJA).update(anulada=False, nota="")
        generar(insc)
        _revisar_terminada(insc)


def adelantar(insc, n=1):
    """Genera los siguientes periodos para pagarlos por adelantado (solo planes sin fin)."""
    if not insc.activa:
        raise CobranzaError("La inscripción no está activa.")
    if not insc.plan.es_indefinido:
        raise CobranzaError("Este plan ya tiene todas sus cuotas generadas.")
    hoy = timezone.localdate()
    generar(insc, hoy)  # primero lo que toca
    return generar(insc, hoy, extra=max(1, min(int(n or 1), 12)))


def exonerar(cuota, usuario, motivo):
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CobranzaError("Indica el motivo.")
    if cuota.anulada:
        raise CobranzaError("Esa cuota ya estaba exonerada.")
    if cuota.pagada:
        raise CobranzaError("Esa cuota ya está pagada.")
    cuota.anulada = True
    cuota.nota = f"Exonerada por {usuario.get_full_name() or usuario.username}: {motivo}"[:200]
    cuota.save(update_fields=["anulada", "nota"])
    _revisar_terminada(cuota.inscripcion)


def quitar_mora(cuota):
    if not cuota.mora:
        raise CobranzaError("Esa cuota no tiene mora.")
    cuota.mora = max(CERO, min(cuota.mora, cuota.pagado - cuota.monto))  # lo que ya pagó de mora no se devuelve
    cuota.mora_perdonada = True
    cuota.save(update_fields=["mora", "mora_perdonada"])
    _revisar_terminada(cuota.inscripcion)


def _revisar_terminada(insc):
    """Un plan con número fijo de cuotas termina cuando no le queda nada por pagar."""
    if insc.plan.es_indefinido or insc.estado == Inscripcion.Estado.BAJA:
        return
    queda = insc.cuotas.filter(anulada=False, pagado__lt=F("monto") + F("mora")).exists()
    if not queda and insc.plan.frecuencia == Plan.Frecuencia.UNICO and insc.plan.duracion_dias:
        fin = vigencia(insc)["hasta"]  # un pase o paquete pagado sigue activo mientras dure
        queda = fin is not None and fin >= timezone.localdate()
    estado = Inscripcion.Estado.ACTIVA if queda else Inscripcion.Estado.TERMINADA
    if insc.estado != estado:
        insc.estado = estado
        insc.fin = None if queda else timezone.localdate()
        insc.save(update_fields=["estado", "fin"])


# --- Cobrar y anular -----------------------------------------------------------------

def pendientes(cliente):
    """Cuotas que le falta pagar al cliente, de la más antigua a la más nueva."""
    return (Cuota.objects.filter(inscripcion__cliente=cliente, anulada=False)
            .annotate(falta=PENDIENTE).filter(falta__gt=0).select_related("inscripcion__plan").order_by("vence", "numero", "id"))


def cobrar(cliente, cuotas_ids, monto, metodo, usuario, nota="", referencia=""):
    """Registra un pago y lo reparte entre las cuotas elegidas, empezando por la más antigua.
    Puede ser menos que el total (pago a cuenta). El dinero entra a la caja abierta de quien cobra."""
    from caja.servicios import CajaError, sesion_para_vender
    from core.models import Ajustes
    from ventas.models import MetodoPago

    monto = _monto(monto)
    if metodo == MetodoPago.CREDITO or metodo not in Ajustes.cargar().metodos_aceptados:
        raise CobranzaError("Método de pago no válido.")
    from ventas.servicios import falta_operacion

    if error := falta_operacion(metodo, referencia):
        raise CobranzaError(error)
    ids = [int(i) for i in cuotas_ids if str(i).isdigit()]
    if not ids:
        raise CobranzaError("Marca qué cuotas paga.")
    try:
        sesion = sesion_para_vender(usuario)
    except CajaError as e:
        raise CobranzaError(str(e))
    from caja.servicios import bloquear_abierta

    with transaction.atomic():
        try:
            bloquear_abierta(sesion)
        except CajaError as e:
            raise CobranzaError(str(e))
        cuotas = list(Cuota.objects.select_for_update().filter(pk__in=ids, inscripcion__cliente=cliente, anulada=False)
                      .order_by("vence", "numero", "id"))
        cuotas = [c for c in cuotas if c.pendiente > 0]
        if not cuotas:
            raise CobranzaError("Esas cuotas ya están pagadas.")
        total = sum((c.pendiente for c in cuotas), CERO)
        if monto > total:
            raise CobranzaError(f"Las cuotas marcadas suman S/ {total:.2f}; no se puede cobrar más.")
        pago = Pago.objects.create(cliente=cliente, monto=monto, metodo=metodo, usuario=usuario, sesion_caja=sesion,
                                   nota=str(nota or "")[:200], referencia=str(referencia or "")[:60])
        resto = monto
        for c in cuotas:
            if resto <= 0:
                break
            aplica = min(resto, c.pendiente)
            PagoCuota.objects.create(pago=pago, cuota=c, monto=aplica)
            c.pagado += aplica
            c.save(update_fields=["pagado"])
            resto -= aplica
        for insc in {c.inscripcion for c in cuotas}:
            _revisar_terminada(insc)
    return pago


def anular_pago(pago, usuario, motivo):
    from caja.servicios import CajaError, devolver_efectivo
    from ventas.models import MetodoPago

    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CobranzaError("Indica el motivo.")
    with transaction.atomic():
        p = Pago.objects.select_for_update(of=("self",)).select_related("sesion_caja").get(pk=pago.pk)
        if p.anulado:
            raise CobranzaError("Ese pago ya estaba anulado.")
        if p.metodo == MetodoPago.EFECTIVO:
            try:
                devolver_efectivo(p.sesion_caja, p.monto, usuario, f"Anulación del recibo {p.numero} de {p.cliente}: {motivo}")
            except CajaError as e:
                raise CobranzaError(str(e))
        insc = set()
        for d in p.detalles.select_related("cuota__inscripcion__plan"):
            c = Cuota.objects.select_for_update().get(pk=d.cuota_id)
            c.pagado = max(CERO, c.pagado - d.monto)
            c.save(update_fields=["pagado"])
            insc.add(d.cuota.inscripcion)
        p.anulado, p.anulado_en, p.anulado_por, p.motivo_anulacion = True, timezone.now(), usuario, motivo
        p.save(update_fields=["anulado", "anulado_en", "anulado_por", "motivo_anulacion"])
        from core.bitacora import anotar

        anotar("cuota.pago_anulado", f"Recibo {p.numero} de {p.cliente} por S/ {p.monto:.2f} anulado: {motivo}", objeto=p, usuario=usuario)
        for i in insc:
            _revisar_terminada(i)
    return p


# --- Consultas para las pantallas ----------------------------------------------------

def vencidas(hoy=None):
    hoy = hoy or timezone.localdate()
    return (Cuota.objects.filter(anulada=False, vence__lt=hoy).annotate(falta=PENDIENTE).filter(falta__gt=0)
            .select_related("inscripcion__cliente", "inscripcion__plan"))


def por_vencer(hoy=None, dias=None):
    hoy = hoy or timezone.localdate()
    dias = Config.cargar().dias_aviso if dias is None else dias
    return (Cuota.objects.filter(anulada=False, vence__gte=hoy, vence__lte=hoy + timedelta(days=dias),
                                 inscripcion__estado=Inscripcion.Estado.ACTIVA)
            .annotate(falta=PENDIENTE).filter(falta__gt=0)
            .select_related("inscripcion__cliente", "inscripcion__plan"))


def agrupar_por_cliente(cuotas, hoy=None):
    """[{cliente, cuotas, total, atraso, quienes}] ordenado por lo que más debe."""
    hoy = hoy or timezone.localdate()
    grupos = {}
    for c in cuotas:
        cli = c.inscripcion.cliente
        g = grupos.setdefault(cli.pk, {"cliente": cli, "cuotas": [], "total": CERO, "atraso": 0, "quienes": []})
        g["cuotas"].append(c)
        g["total"] += c.falta
        g["atraso"] = max(g["atraso"], (hoy - c.vence).days)
        if c.inscripcion.quien not in g["quienes"]:
            g["quienes"].append(c.inscripcion.quien)
    for g in grupos.values():
        g["cuotas"].sort(key=lambda c: (c.vence, c.numero))
    return sorted(grupos.values(), key=lambda g: (-g["total"], g["cliente"].nombre))


def mensaje(cliente, cuotas, hoy=None):
    """Texto del recordatorio por WhatsApp."""
    from core.models import Ajustes

    hoy = hoy or timezone.localdate()
    negocio = Ajustes.cargar().nombre_mostrar
    nombre = cliente.nombre.split()[0].title() if cliente.nombre else ""
    lineas = []
    total = CERO
    for c in cuotas:
        falta = getattr(c, "falta", None) or c.pendiente
        total += falta
        quien = f" de {c.inscripcion.alumno}" if c.inscripcion.alumno else ""
        cuando = f"venció el {c.vence:%d/%m}" if c.vence < hoy else ("vence hoy" if c.vence == hoy else f"vence el {c.vence:%d/%m}")
        lineas.append(f"• {c.concepto}{quien} ({c.inscripcion.plan.nombre}): S/ {falta:.2f}, {cuando}")
    texto = f"Hola {nombre}, te saludamos de {negocio}. Te recordamos lo pendiente:\n" + "\n".join(lineas)
    if len(lineas) > 1:
        texto += f"\nTotal: S/ {total:.2f}"
    return texto + "\n¡Gracias!"


def enlace_whatsapp(cliente, cuotas, hoy=None):
    if not cliente.whatsapp:
        return ""
    return _enlace_wa(cliente.telefono, mensaje(cliente, cuotas, hoy))


def resumen(hoy=None):
    """Números de la pantalla de inicio de Cobranzas."""
    hoy = hoy or timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    venc = vencidas(hoy)
    pagos_mes = Pago.objects.filter(anulado=False, **dias("fecha", inicio_mes, hoy))
    return {
        "vencido": venc.aggregate(t=Sum("falta"))["t"] or CERO,
        "morosos": venc.values("inscripcion__cliente").distinct().count(),
        "por_vencer": por_vencer(hoy).aggregate(t=Sum("falta"))["t"] or CERO,
        "cobrado_mes": pagos_mes.aggregate(t=Sum("monto"))["t"] or CERO,
        "cobrado_hoy": pagos_mes.filter(**dias("fecha", hoy)).aggregate(t=Sum("monto"))["t"] or CERO,
        "activos": Inscripcion.objects.filter(estado=Inscripcion.Estado.ACTIVA).count(),
    }


# --- Gimnasios: vigencia, control de ingreso y congelar ------------------------------
# La vigencia sale de las mismas cuotas: cada cuota cubre su periodo (desde que vence hasta que vence la siguiente).
# El socio está al día mientras las cuotas pagadas (o exoneradas) lleguen hasta hoy. No hay una fecha aparte que cuadrar.

def _cubierta(q):
    """La cuota ya da derecho a entrar: pagada (la mora no cuenta) o exonerada (beca). La quitada por baja no."""
    return q.pagado >= q.monto or (q.anulada and q.nota != POR_BAJA)


def _congelados(insc):
    return list(insc.congelamientos.all())


def vigencia(insc, hoy=None):
    """Hasta cuándo puede entrar y el periodo pagado en el que está hoy.

    {"hasta": fecha o None (no vence), "desde": inicio del periodo de hoy, "fin_periodo": último día de ese periodo,
     "debe_desde": la primera cuota sin pagar (o None)}. Con `hasta` menor que el inicio, todavía no pagó nada."""
    hoy = hoy or timezone.localdate()
    plan = insc.plan
    cuotas = [q for q in insc.cuotas.all() if q.numero > 0]
    cuotas.sort(key=lambda q: q.numero)
    if plan.frecuencia == Plan.Frecuencia.UNICO:
        pagada = bool(cuotas) and _cubierta(cuotas[0])
        if not plan.duracion_dias:
            fin = None
        else:
            extra = sum(c.dias for c in _congelados(insc))
            fin = insc.inicio + timedelta(days=plan.duracion_dias - 1 + extra)
        return {"hasta": fin if pagada else insc.inicio - timedelta(days=1), "desde": insc.inicio, "fin_periodo": fin,
                "debe_desde": None if pagada else (cuotas[0] if cuotas else None)}
    hasta, desde, debe = insc.inicio - timedelta(days=1), insc.inicio, None
    for i, q in enumerate(cuotas):
        if not _cubierta(q):
            debe = q
            break
        siguiente = cuotas[i + 1].vence if i + 1 < len(cuotas) else siguiente_vence(insc, q.vence)
        hasta = siguiente - timedelta(days=1)
        if q.vence <= hoy:
            desde = q.vence
    # el periodo que contiene hoy (para contar clases), aunque no esté pagado
    fin_periodo = hasta
    for i, q in enumerate(cuotas):
        siguiente = cuotas[i + 1].vence if i + 1 < len(cuotas) else siguiente_vence(insc, q.vence)
        if q.vence <= hoy < siguiente:
            desde, fin_periodo = q.vence, siguiente - timedelta(days=1)
    return {"hasta": hasta, "desde": desde, "fin_periodo": fin_periodo, "debe_desde": debe}


def congelado_hoy(insc, hoy=None):
    hoy = hoy or timezone.localdate()
    return next((c for c in _congelados(insc) if c.desde <= hoy <= c.hasta), None)


def estado_ingreso(insc, hoy=None, cfg=None):
    """¿Puede entrar hoy? Lo que se muestra en la puerta:
    {"puede", "color" (success/warning/danger/secondary), "titulo", "detalle", "hasta", "clases", "quedan", "hoy_entro"}."""
    hoy = hoy or timezone.localdate()
    cfg = cfg or Config.cargar()
    v = vigencia(insc, hoy)
    e = {"puede": False, "color": "danger", "titulo": "", "detalle": "", "hasta": v["hasta"], "clases": insc.plan.clases,
         "quedan": None, "hoy_entro": None, "debe": CERO}
    entradas = [a for a in insc.asistencias.all() if timezone.localtime(a.fecha).date() == hoy]
    e["hoy_entro"] = timezone.localtime(entradas[0].fecha) if entradas else None
    deuda = sum((q.pendiente for q in insc.cuotas.all() if q.vence <= hoy), CERO)
    e["debe"] = deuda
    if insc.estado == Inscripcion.Estado.BAJA:
        e.update(color="secondary", titulo="De baja", detalle=f"Se dio de baja el {insc.fin:%d/%m/%Y}." if insc.fin else "")
        return e
    if insc.inicio > hoy:
        e.update(color="secondary", titulo=f"Empieza el {insc.inicio:%d/%m}")
        return e
    cong = congelado_hoy(insc, hoy)
    if cong:
        e.update(color="info", titulo=f"Congelado hasta el {cong.hasta:%d/%m}", detalle=cong.motivo)
        return e
    hasta = v["hasta"]
    if hasta is not None and hasta < hoy:
        vencio = hasta + timedelta(days=1)
        if hasta >= insc.inicio or v["debe_desde"] is None:
            texto = f"Venció el {hasta:%d/%m}"
        else:
            texto = "Aún no paga"
        recurrente = insc.plan.frecuencia != Plan.Frecuencia.UNICO  # un pase o paquete vencido no tiene tolerancia
        if recurrente and (hoy - vencio).days < cfg.dias_tolerancia and hasta >= insc.inicio:
            e.update(puede=True, color="warning", titulo=texto,
                     detalle=f"Puede entrar hasta el {vencio + timedelta(days=cfg.dias_tolerancia - 1):%d/%m} (tolerancia). Recuérdale pagar.")
        else:
            e.update(titulo=texto, detalle=f"Debe S/ {deuda:.2f}" if deuda else "")
            return e
    if insc.plan.clases:
        usadas = sum(1 for a in insc.asistencias.all() if v["desde"] <= timezone.localtime(a.fecha).date() <= (v["fin_periodo"] or hoy))
        e["quedan"] = max(0, insc.plan.clases - usadas)
        if e["quedan"] == 0 and not e["hoy_entro"]:
            e.update(puede=False, color="danger", titulo="Ya usó sus clases",
                     detalle=f"Usó las {insc.plan.clases} de este periodo" + (f" (hasta el {v['fin_periodo']:%d/%m})." if v["fin_periodo"] else "."))
            return e
    if e["color"] != "warning":
        e["puede"] = True
    if e["color"] == "warning":
        pass  # en tolerancia: ya tiene su título
    elif hasta is None:
        e.update(color="success", titulo="Al día")
    elif (hasta - hoy).days < 3:
        e.update(color="warning", titulo=f"Al día hasta el {hasta:%d/%m}", detalle="Vence pronto: recuérdale renovar.")
    else:
        e.update(color="success", titulo=f"Al día hasta el {hasta:%d/%m}")
    if e["quedan"] is not None:
        e["detalle"] = (e["detalle"] + " " if e["detalle"] else "") + (f"Le queda 1 clase." if e["quedan"] == 1 else f"Le quedan {e['quedan']} clases.")
    return e


def para_ingreso(inscripciones):
    """Las inscripciones con lo que hace falta para mostrarlas en la puerta (pocas consultas)."""
    return (inscripciones.select_related("cliente", "plan")
            .prefetch_related("cuotas", "congelamientos", "asistencias"))


def registrar_ingreso(insc, usuario, permitir=False, nota="", hoy=None):
    """Anota que el socio entró. Si no está al día, solo entra con `permitir` y un motivo (queda en la bitácora).
    Una vez por día: si ya entró hoy, no se cuenta de nuevo (no gasta otra clase)."""
    from core.bitacora import anotar

    e = estado_ingreso(insc, hoy)
    if e["hoy_entro"]:
        raise CobranzaError(f"{insc.quien} ya entró hoy a las {e['hoy_entro']:%H:%M}.")
    nota = " ".join(str(nota or "").split())[:200]
    if not e["puede"]:
        if insc.estado == Inscripcion.Estado.BAJA:
            raise CobranzaError(f"{insc.quien} está de baja.")
        if not permitir:
            raise CobranzaError(f"{insc.quien}: {e['titulo'].lower()}. Para dejarlo pasar igual, indica el motivo.")
        if not nota:
            raise CobranzaError("Indica el motivo para dejarlo pasar (por ejemplo: «paga a la salida»).")
    a = Asistencia.objects.create(inscripcion=insc, usuario=usuario, con_permiso=not e["puede"], nota=nota)
    if not e["puede"]:
        anotar("socio.ingreso_sin_pago", f"{insc.quien} ({insc.plan.nombre}) entró sin estar al día: {e['titulo']}. Motivo: {nota}",
               objeto=insc, usuario=usuario)
    return a


def codigo_carne(insc):
    """Lo que lleva el QR del carné: SOCIO-<id>-<firma>. La firma evita que alguien invente el código de otro."""
    from django.core.signing import Signer

    return f"SOCIO-{insc.pk}-{Signer(salt='carne').signature(str(insc.pk))[:8]}"


def por_codigo(texto):
    """La inscripción de un código de carné leído con la cámara o el lector (o None)."""
    import re

    m = re.fullmatch(r"\s*SOCIO-(\d+)-([\w-]{8})\s*", str(texto or ""), re.I)
    if not m:
        return None
    insc = Inscripcion.objects.filter(pk=int(m.group(1))).first()
    return insc if insc and codigo_carne(insc).upper() == str(texto).strip().upper() else None


def dias_congelados(insc, anio):
    return sum(min(c.hasta, date(anio, 12, 31)).toordinal() - max(c.desde, date(anio, 1, 1)).toordinal() + 1
               for c in insc.congelamientos.all() if c.desde.year <= anio <= c.hasta.year)


def _correr(insc, despues_de, dias):
    """Corre `dias` las cuotas que vencen después de `despues_de` (y el día de pago de los planes por meses)."""
    cuotas = list(insc.cuotas.filter(numero__gt=0, vence__gt=despues_de))
    for q in cuotas:
        q.vence += timedelta(days=dias)
    if cuotas:
        Cuota.objects.bulk_update(cuotas, ["vence"])
        if insc.plan.frecuencia in MESES_POR:
            insc.dia_pago = min(cuotas, key=lambda q: q.vence).vence.day
            insc.save(update_fields=["dia_pago"])


def congelar(insc, desde, dias, motivo, usuario, hoy=None):
    """Pausa la membresía `dias` días desde `desde`: esos días no entra y todo lo que vence después se corre."""
    from core.bitacora import anotar

    hoy = hoy or timezone.localdate()
    cfg = Config.cargar()
    if not cfg.congelar_dias:
        raise CobranzaError("Congelar no está permitido (Cobranzas → Configuración).")
    if insc.estado == Inscripcion.Estado.BAJA:
        raise CobranzaError("La inscripción está de baja.")
    if insc.plan.frecuencia == Plan.Frecuencia.UNICO and not insc.plan.duracion_dias:
        raise CobranzaError("Este plan no vence: no hace falta congelarlo.")
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CobranzaError("Indica el motivo (viaje, lesión…).")
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        raise CobranzaError("Indica cuántos días.")
    if desde is None or desde < hoy:
        raise CobranzaError("El congelamiento empieza hoy o después.")
    usados = dias_congelados(insc, desde.year)
    libres = cfg.congelar_dias - usados
    if dias < 1 or dias > libres:
        raise CobranzaError(f"Puede congelar hasta {libres} día{'s' if libres != 1 else ''} más este año (usó {usados} de {cfg.congelar_dias})."
                            if libres > 0 else f"Ya usó sus {cfg.congelar_dias} días de congelamiento de este año.")
    hasta = desde + timedelta(days=dias - 1)
    if any(c.desde <= hasta and desde <= c.hasta for c in insc.congelamientos.all()):
        raise CobranzaError("Ya tiene un congelamiento en esas fechas.")
    with transaction.atomic():
        if insc.plan.es_indefinido:  # que exista la cuota que vence después del congelamiento, para correrla
            for _ in range(24):
                ultima = insc.cuotas.filter(numero__gt=0).order_by("-numero").first()
                if ultima and ultima.vence > desde:
                    break
                generar(insc, hoy, extra=1)
        c = Congelamiento.objects.create(inscripcion=insc, desde=desde, hasta=hasta, motivo=motivo, usuario=usuario)
        if insc.plan.frecuencia != Plan.Frecuencia.UNICO:
            _correr(insc, desde, dias)
        anotar("socio.congelado", f"{insc.quien} ({insc.plan.nombre}): congelado del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}. {motivo}",
               objeto=insc, usuario=usuario)
    return c


def descongelar(cong, usuario, hoy=None):
    """Vuelve antes: el congelamiento termina ayer (o se quita si aún no empezaba) y lo que se corrió de más regresa."""
    from core.bitacora import anotar

    hoy = hoy or timezone.localdate()
    if cong.hasta < hoy:
        raise CobranzaError("Ese congelamiento ya terminó.")
    insc = cong.inscripcion
    nuevo_hasta = hoy - timedelta(days=1)
    sobran = (cong.hasta - max(nuevo_hasta, cong.desde - timedelta(days=1))).days
    with transaction.atomic():
        if insc.plan.frecuencia != Plan.Frecuencia.UNICO:
            _correr(insc, cong.hasta, -sobran)
        if nuevo_hasta < cong.desde:
            cong.delete()
        else:
            cong.hasta = nuevo_hasta
            cong.save(update_fields=["hasta"])
        anotar("socio.congelado", f"{insc.quien} ({insc.plan.nombre}): volvió antes; se devolvieron {sobran} día{'s' if sobran != 1 else ''}.",
               objeto=insc, usuario=usuario)
    return sobran
