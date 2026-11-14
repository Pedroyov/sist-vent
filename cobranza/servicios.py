"""
Reglas de negocio de la cobranza. Las vistas y señales llaman a estas funciones
para que la lógica esté en un solo lugar.
"""
import calendar
from datetime import date

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from alumnos.models import Matricula

from .models import CERO, MESES, Cargo, ConfigCobranza, Concepto, Descuento, Pago, PagoDetalle, dinero


# --- Cronograma (conceptos) -------------------------------------------------

@transaction.atomic
def generar_conceptos(config: ConfigCobranza):
    """
    Crea o actualiza la matrícula y una pensión por mes según la configuración.
    Si cambian los montos, se actualizan también las deudas que aún no tienen pagos.
    Devuelve una lista de avisos (por ejemplo, meses que no se pudieron quitar).
    """
    anio = config.anio_lectivo
    avisos = []

    mat, _ = Concepto.objects.update_or_create(
        anio_lectivo=anio, tipo=Concepto.Tipo.MATRICULA,
        defaults={"nombre": f"Matrícula {anio}", "monto": config.monto_matricula,
                  "vencimiento": anio.fecha_inicio, "automatico": True},
    )
    vigentes = [mat.pk]
    for mes in config.meses:
        c, _ = Concepto.objects.update_or_create(
            anio_lectivo=anio, tipo=Concepto.Tipo.PENSION, mes=mes,
            defaults={"nombre": f"Pensión {MESES[mes]}", "monto": config.monto_pension,
                      "vencimiento": config.vencimiento_de(mes), "automatico": True},
        )
        vigentes.append(c.pk)

    # pensiones de meses que ya no están en el rango
    for c in Concepto.objects.filter(anio_lectivo=anio, tipo=Concepto.Tipo.PENSION).exclude(pk__in=vigentes):
        if c.cargos.filter(pagado__gt=0).exists():
            avisos.append(f"«{c.nombre}» tiene pagos registrados y no se eliminó.")
            continue
        c.cargos.all().delete()
        c.delete()

    # actualizar montos y vencimientos de deudas sin pagos
    for c in Concepto.objects.filter(pk__in=vigentes):
        c.cargos.filter(pagado=0).update(monto=c.monto, vencimiento=c.vencimiento)
    for alumno_id in Cargo.objects.filter(concepto__anio_lectivo=anio).values_list("alumno_id", flat=True).distinct():
        recalcular_descuentos(alumno_id, anio)
    return avisos


# --- Deudas por alumno ------------------------------------------------------

def _descuento_para(concepto, descuentos):
    total = CERO
    for d in descuentos:
        if d.aplica_a(concepto):
            total += d.calcular(concepto.monto - total)
    return min(total, concepto.monto)


@transaction.atomic
def asignar_cargos(matricula: Matricula):
    """Crea las deudas automáticas (matrícula y pensiones) de un alumno matriculado."""
    if matricula.estado != Matricula.Estado.MATRICULADO:
        return 0
    anio = matricula.anio_lectivo
    conceptos = Concepto.objects.filter(anio_lectivo=anio, automatico=True)
    existentes = set(Cargo.objects.filter(alumno=matricula.alumno, concepto__in=conceptos).values_list("concepto_id", flat=True))
    descuentos = list(Descuento.objects.filter(alumno=matricula.alumno, anio_lectivo=anio))
    nuevos = []
    for c in conceptos:
        if c.pk in existentes:
            continue
        # quien se matricula a mitad de año no debe los meses anteriores
        if c.tipo == Concepto.Tipo.PENSION and matricula.fecha.year == anio.anio and c.mes < matricula.fecha.month:
            continue
        nuevos.append(Cargo(alumno=matricula.alumno, concepto=c, monto=c.monto,
                            descuento=_descuento_para(c, descuentos), vencimiento=c.vencimiento))
    Cargo.objects.bulk_create(nuevos)
    return len(nuevos)


@transaction.atomic
def actualizar_por_estado(matricula: Matricula):
    """Si el alumno se retira, deja de cobrar lo que vence después del mes del retiro (y no tiene pagos)."""
    cargos = Cargo.objects.filter(alumno=matricula.alumno, concepto__anio_lectivo=matricula.anio_lectivo, pagado=0)
    if matricula.estado == Matricula.Estado.MATRICULADO:
        cargos.filter(anulado=True).update(anulado=False)
    else:
        # se cobra hasta el mes del retiro (inclusive)
        retiro = matricula.fecha_retiro or timezone.localdate()
        corte = date(retiro.year, retiro.month, calendar.monthrange(retiro.year, retiro.month)[1])
        cargos.filter(vencimiento__gt=corte).update(anulado=True)


def sincronizar_anio(anio):
    """Asigna las deudas automáticas a todos los matriculados del año. Se puede repetir sin duplicar."""
    total = 0
    for m in Matricula.objects.filter(anio_lectivo=anio, estado=Matricula.Estado.MATRICULADO).select_related("alumno", "anio_lectivo"):
        total += asignar_cargos(m)
    return total


@transaction.atomic
def recalcular_descuentos(alumno_id, anio):
    descuentos = list(Descuento.objects.filter(alumno_id=alumno_id, anio_lectivo=anio))
    for cargo in Cargo.objects.filter(alumno_id=alumno_id, concepto__anio_lectivo=anio).select_related("concepto"):
        nuevo = _descuento_para(cargo.concepto, descuentos)
        nuevo = min(nuevo, max(cargo.monto - cargo.pagado, CERO))  # no bajar de lo ya pagado
        if nuevo != cargo.descuento:
            cargo.descuento = nuevo
            cargo.save(update_fields=["descuento"])


# --- Pagos ------------------------------------------------------------------

class ErrorPago(Exception):
    pass


@transaction.atomic
def registrar_pago(*, alumno, anio, items, usuario, fecha=None, metodo=Pago.Metodo.EFECTIVO,
                   numero_operacion="", voucher=None, observacion=""):
    """
    items: lista de (cargo_id, monto, mora). Valida que nadie pague más de lo que debe.
    """
    if not items:
        raise ErrorPago("Selecciona al menos una deuda a pagar.")
    cargos = {c.pk: c for c in Cargo.objects.select_for_update().filter(
        pk__in=[i[0] for i in items], alumno=alumno, anulado=False)}
    detalles, total = [], CERO
    for cargo_id, monto, mora in items:
        cargo = cargos.get(cargo_id)
        if cargo is None:
            raise ErrorPago("Una de las deudas ya no existe o fue anulada. Recarga la página.")
        if monto < 0 or mora < 0:
            raise ErrorPago("Los montos no pueden ser negativos.")
        if monto > cargo.saldo:
            raise ErrorPago(f"«{cargo.concepto}»: el monto (S/ {monto}) es mayor que el saldo (S/ {cargo.saldo}).")
        if monto == 0 and mora == 0:
            continue
        detalles.append((cargo, monto, mora))
        total += monto + mora
    if total <= 0:
        raise ErrorPago("El total a pagar debe ser mayor que cero.")

    ultimo = Pago.objects.select_for_update().filter(anio_lectivo=anio).aggregate(m=Max("numero"))["m"] or 0
    pago = Pago.objects.create(
        anio_lectivo=anio, numero=ultimo + 1, alumno=alumno, fecha=fecha or timezone.localdate(),
        metodo=metodo, numero_operacion=numero_operacion, voucher=voucher or "",
        total=total, observacion=observacion, registrado_por=usuario,
    )
    for cargo, monto, mora in detalles:
        PagoDetalle.objects.create(pago=pago, cargo=cargo, monto=monto, mora=mora)
        cargo.pagado += monto
        cargo.save(update_fields=["pagado"])
    return pago


@transaction.atomic
def anular_pago(pago: Pago, usuario, motivo):
    if pago.anulado:
        raise ErrorPago("Este pago ya está anulado.")
    for d in pago.detalles.select_related("cargo").select_for_update():
        d.cargo.pagado = max(d.cargo.pagado - d.monto, CERO)
        d.cargo.save(update_fields=["pagado"])
    pago.anulado = True
    pago.anulado_por = usuario
    pago.anulado_en = timezone.now()
    pago.motivo_anulacion = motivo
    pago.save(update_fields=["anulado", "anulado_por", "anulado_en", "motivo_anulacion"])


# --- Consultas --------------------------------------------------------------

def resumen_alumno(alumno, anio, hoy=None):
    hoy = hoy or timezone.localdate()
    config = ConfigCobranza.objects.filter(anio_lectivo=anio).first()
    cargos = list(Cargo.objects.filter(alumno=alumno, concepto__anio_lectivo=anio).select_related("concepto"))
    for c in cargos:
        c.mora_hoy = c.mora(config, hoy)
    vigentes = [c for c in cargos if not c.anulado]
    return {
        "config": config,
        "cargos": cargos,
        "total": sum((c.total for c in vigentes), CERO),
        "pagado": sum((c.pagado for c in vigentes), CERO),
        "saldo": sum((c.saldo for c in vigentes), CERO),
        "vencido": sum((c.saldo for c in vigentes if c.vencimiento < hoy), CERO),
        "mora": sum((c.mora_hoy for c in vigentes), CERO),
        "n_vencidos": sum(1 for c in vigentes if c.saldo > 0 and c.vencimiento < hoy),
    }


def cobrado_en(desde: date, hasta: date):
    return dinero(Pago.objects.filter(anulado=False, fecha__range=(desde, hasta)).aggregate(t=Sum("total"))["t"] or CERO)
