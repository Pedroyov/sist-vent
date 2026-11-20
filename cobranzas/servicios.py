"""Inscribir, generar cuotas, cobrar, anular, dar de baja. Las reglas de cobranza están todas aquí."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from core.utils import enlace_whatsapp as _enlace_wa

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.utils import timezone

from .models import CERO, Config, Cuota, Inscripcion, Pago, PagoCuota, Plan

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


def vence_cuota(insc, k):
    """Fecha en que vence la cuota k (1, 2, 3…). La primera vence el día que empieza."""
    f = insc.plan.frecuencia
    if k <= 1 or f == Plan.Frecuencia.UNICO:
        return insc.inicio
    if f == Plan.Frecuencia.SEMANAL:
        return insc.inicio + timedelta(days=7 * (k - 1))
    if f == Plan.Frecuencia.QUINCENAL:
        return insc.inicio + timedelta(days=15 * (k - 1))
    # Mensual: desde el segundo mes vence en su día de pago
    return sumar_meses(insc.inicio, k - 1, insc.dia_pago)


def concepto_cuota(insc, k, vence):
    plan = insc.plan
    if plan.frecuencia == Plan.Frecuencia.UNICO:
        return plan.nombre[:80]
    if plan.num_cuotas:
        return f"Cuota {k} de {plan.num_cuotas}"
    if plan.frecuencia == Plan.Frecuencia.MENSUAL:
        return f"Mensualidad {MESES[vence.month - 1]} {vence.year}"
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
    ultima = insc.cuotas.filter(numero__gt=0).aggregate(n=Max("numero"))["n"] or 0
    tope = total_cuotas(insc.plan)
    nuevas = []
    k = ultima + 1
    while tope is None or k <= tope:
        vence = vence_cuota(insc, k)
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
    pagos_mes = Pago.objects.filter(anulado=False, fecha__date__gte=inicio_mes, fecha__date__lte=hoy)
    return {
        "vencido": venc.aggregate(t=Sum("falta"))["t"] or CERO,
        "morosos": venc.values("inscripcion__cliente").distinct().count(),
        "por_vencer": por_vencer(hoy).aggregate(t=Sum("falta"))["t"] or CERO,
        "cobrado_mes": pagos_mes.aggregate(t=Sum("monto"))["t"] or CERO,
        "cobrado_hoy": pagos_mes.filter(fecha__date=hoy).aggregate(t=Sum("monto"))["t"] or CERO,
        "activos": Inscripcion.objects.filter(estado=Inscripcion.Estado.ACTIVA).count(),
    }
