"""Saldo a favor del cliente: dinero que ya dejó en el negocio y usa para pagar después.

Entra con una devolución a saldo (ventas/devoluciones.py). Sale cuando paga una compra con el método «Saldo a favor»
(ventas.servicios.registrar_venta), o cuando se le devuelve en efectivo desde una caja abierta (con permiso y motivo).
Usar el saldo no es dinero que entra: no suma a la caja, ni a la conciliación, ni a Dinero del día.

Monedero (función «Monedero»): un % de lo pagado por un cliente registrado entra como saldo que vence (por defecto a los
90 días). Lo fiado da monedero cuando se paga. Si la venta se devuelve o se anula, se descuenta lo que generó.
Al usar el saldo se gasta primero lo que vence antes; lo vencido sin usar deja de contar.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .models import Cliente, MovimientoSaldo

CERO = Decimal("0")


class SaldoError(Exception):
    pass


def _lotes(movimientos):
    """Lo que queda de cada entrada [monto, vence] después de las salidas: cada salida gasta primero lo que vence antes
    (y no toca lo que ya había vencido en ese momento)."""
    lotes = []
    for m in sorted(movimientos, key=lambda m: (m.fecha, m.pk)):
        if m.anulado:
            continue
        if m.entra:
            lotes.append([m.monto, m.vence])
            continue
        dia, falta = timezone.localtime(m.fecha).date(), m.monto
        for lote in sorted(lotes, key=lambda x: x[1] or date.max):
            if falta <= 0:
                break
            if lote[1] and lote[1] < dia:
                continue
            usado = min(lote[0], falta)
            lote[0] -= usado
            falta -= usado
    return lotes


def saldo_a_favor(cliente, hoy=None):
    hoy = hoy or timezone.localdate()
    lotes = _lotes(MovimientoSaldo.objects.filter(cliente=cliente))
    return sum((m for m, vence in lotes if not vence or vence >= hoy), CERO).quantize(Decimal("0.01"))


def por_vencer(cliente, dias=30):
    """(monto, fecha) de monedero que vence en los próximos días (el más próximo), o None."""
    hoy = timezone.localdate()
    proximos = sorted((vence, m) for m, vence in _lotes(MovimientoSaldo.objects.filter(cliente=cliente))
                      if vence and m > 0 and hoy <= vence <= hoy + timedelta(days=dias))
    return (proximos[0][1], proximos[0][0]) if proximos else None


def total_a_favor():
    """Lo que el negocio debe a todos sus clientes en saldo a favor (para Reportes)."""
    from collections import defaultdict

    hoy, por_cliente = timezone.localdate(), defaultdict(list)
    for m in MovimientoSaldo.objects.all():
        por_cliente[m.cliente_id].append(m)
    return sum((m for movs in por_cliente.values() for m, vence in _lotes(movs) if not vence or vence >= hoy), CERO).quantize(Decimal("0.01"))


def abonar(cliente, monto, tipo, usuario, nota="", **ligado):
    """Suma saldo (dentro de la transacción de quien llama: una devolución)."""
    return MovimientoSaldo.objects.create(cliente=cliente, monto=monto, tipo=tipo, usuario=usuario, nota=str(nota or "")[:200], **ligado)


def usar(cliente, monto, venta, usuario):
    """Paga parte o toda una venta con el saldo. Bloquea al cliente: dos cajas no pueden gastar el mismo saldo."""
    Cliente.objects.select_for_update().get(pk=cliente.pk)
    disponible = saldo_a_favor(cliente)
    if monto > disponible:
        raise SaldoError(f"{cliente.nombre} tiene S/ {disponible:.2f} de saldo a favor.")
    return MovimientoSaldo.objects.create(cliente=cliente, monto=monto, tipo=MovimientoSaldo.Tipo.USO, venta=venta, usuario=usuario,
                                          nota=f"Venta {venta.numero_str}")


def devolver_uso(venta):
    """Al anular una venta pagada con saldo, el saldo vuelve al cliente."""
    MovimientoSaldo.objects.filter(venta=venta, tipo=MovimientoSaldo.Tipo.USO, anulado=False).update(anulado=True)


def reintegrar(cliente, monto, usuario, motivo):
    """Devuelve saldo a favor en efectivo, desde la caja abierta de quien lo hace (egreso «Devolución»)."""
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import movimiento
    from core.bitacora import anotar

    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise SaldoError("Indica el motivo.")
    try:
        monto = Decimal(str(monto).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        raise SaldoError("Monto no válido.")
    if monto <= 0:
        raise SaldoError("El monto debe ser mayor que cero.")
    with transaction.atomic():
        Cliente.objects.select_for_update().get(pk=cliente.pk)
        disponible = saldo_a_favor(cliente)
        if monto > disponible:
            raise SaldoError(f"Solo tiene S/ {disponible:.2f} de saldo a favor.")
        sesion = SesionCaja.abierta_de(usuario)
        if sesion is None:
            raise SaldoError("Para devolver en efectivo abre tu caja primero: así la salida queda registrada.")
        m = movimiento(sesion, MovimientoCaja.Tipo.EGRESO, monto, f"Saldo a favor devuelto a {cliente.nombre}: {motivo}"[:150], usuario,
                       MovimientoCaja.Categoria.DEVOLUCION, automatico=True)
        mov = MovimientoSaldo.objects.create(cliente=cliente, monto=monto, tipo=MovimientoSaldo.Tipo.REINTEGRO, movimiento=m, usuario=usuario,
                                             nota=motivo)
        anotar("cliente.saldo_devuelto", f"S/ {monto:.2f} de saldo a favor devueltos en efectivo a {cliente.nombre}: {motivo}",
               objeto=cliente, usuario=usuario, despues={"monto": monto, "queda": disponible - monto})
    return mov


# --- Monedero --------------------------------------------------------------------------------

def _monedero():
    from core.models import Ajustes

    a = Ajustes.cargar()
    return a if a.usa_monedero and a.monedero_porcentaje > 0 else None


def _porcentaje(monto, ajustes):
    return (monto * ajustes.monedero_porcentaje / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ganar_por_venta(venta, usuario):
    """El % de lo pagado en la venta (sin fiado, sin lo pagado con saldo y sin propina). Dentro de la transacción de la venta."""
    from ventas.models import MetodoPago

    a = _monedero()
    if a is None or venta.cliente_id is None:
        return None
    pagado = sum((p.monto for p in venta.pagos.all() if p.metodo not in (MetodoPago.CREDITO, MetodoPago.SALDO)), CERO)
    monto = _porcentaje(min(pagado, venta.total), a)
    if monto <= 0:
        return None
    return MovimientoSaldo.objects.create(cliente_id=venta.cliente_id, monto=monto, tipo=MovimientoSaldo.Tipo.MONEDERO, venta=venta,
                                          vence=timezone.localdate() + timedelta(days=a.monedero_dias), usuario=usuario,
                                          nota=f"Venta {venta.numero_str}")


def ganar_por_pago(abono):
    """El fiado da monedero cuando se paga."""
    a = _monedero()
    if a is None or abono.metodo in ("INC", "DEV"):
        return None
    monto = _porcentaje(abono.monto, a)
    if monto <= 0:
        return None
    return MovimientoSaldo.objects.create(cliente_id=abono.cliente_id, monto=monto, tipo=MovimientoSaldo.Tipo.MONEDERO, abono=abono,
                                          vence=timezone.localdate() + timedelta(days=a.monedero_dias), usuario=abono.usuario,
                                          nota=f"Pago {abono.numero}")


def quitar(cliente_id, ganado, usuario, nota, venta=None, devolucion=None):
    """Descuenta monedero ganado (una devolución, una venta o un pago anulados). Nunca deja el saldo en negativo:
    si el cliente ya lo usó, se descuenta lo que quede."""
    if not ganado or ganado <= 0:
        return None
    cliente = Cliente.objects.select_for_update().get(pk=cliente_id)
    monto = min(ganado.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), saldo_a_favor(cliente))
    if monto <= 0:
        return None
    return MovimientoSaldo.objects.create(cliente=cliente, monto=monto, tipo=MovimientoSaldo.Tipo.QUITA, venta=venta, devolucion=devolucion,
                                          usuario=usuario, nota=str(nota)[:200])


def ganado_en(venta):
    return sum((m.monto for m in MovimientoSaldo.objects.filter(venta=venta, tipo=MovimientoSaldo.Tipo.MONEDERO, anulado=False)), CERO)


def del_ticket(venta):
    """«Ganaste S/ 0.60 · tu saldo: S/ 4.20» para el ticket (o None)."""
    if not venta.cliente_id:
        return None
    ganado = ganado_en(venta)
    return {"ganado": ganado, "saldo": saldo_a_favor(venta.cliente)} if ganado else None
