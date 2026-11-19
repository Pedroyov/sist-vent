"""Pagos al personal (función «pagos»): lo que le toca a cada persona en un periodo frente a lo que ya se le pagó.

- Le toca = sueldo fijo del periodo (por semana, quincena o mes, contado día por día) + comisión (si el negocio paga
  comisiones; la calcula personal/reportes.py).
- Pagado = los egresos «Pago o adelanto a personal» ligados a la persona, de cualquier caja o fuera de caja.
"""
import calendar
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Sum

CERO = Decimal("0")


def _dias_de(d, cada):
    """Entre cuántos días se reparte el sueldo que cubre el día d."""
    if cada == "SEM":
        return 7
    dias_mes = calendar.monthrange(d.year, d.month)[1]
    if cada == "QUI":
        return 15 if d.day <= 15 else dias_mes - 15
    return dias_mes


def sueldo_del_periodo(persona, desde, hasta):
    """El sueldo que corresponde a esos días (un mes completo = el sueldo; medio mes = la mitad)."""
    if not persona.sueldo:
        return CERO
    total, d = Decimal(0), desde
    while d <= hasta:
        total += persona.sueldo / _dias_de(d, persona.sueldo_cada)
        d += timedelta(days=1)
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cuentas(desde, hasta):
    from caja.models import MovimientoCaja
    from core.models import Ajustes

    from .models import Persona
    from .reportes import de_negocio

    pagado = {r["persona_id"]: r for r in MovimientoCaja.objects
              .filter(categoria=MovimientoCaja.Categoria.PERSONAL, tipo=MovimientoCaja.Tipo.EGRESO, persona__isnull=False,
                      fecha__date__gte=desde, fecha__date__lte=hasta)
              .values("persona_id").annotate(total=Sum("monto"), n=Count("id"))}
    comisiones = {}
    if Ajustes.cargar().usa_comisiones:
        comisiones = {f["persona"].pk: f["comision"] or CERO for f in de_negocio(desde, hasta)["filas"] if f["persona"]}
    filas = []
    for p in Persona.objects.all():
        sueldo = sueldo_del_periodo(p, desde, hasta) if p.activo else CERO
        comision = comisiones.get(p.pk, CERO)
        pago = pagado.get(p.pk, {})
        if not (sueldo or comision or pago):
            continue
        toca = sueldo + comision
        total_pagado = pago.get("total") or CERO
        filas.append({"persona": p, "sueldo": sueldo, "comision": comision, "toca": toca, "pagado": total_pagado,
                      "pagos": pago.get("n", 0), "falta": toca - total_pagado})
    suma = lambda k: sum((f[k] for f in filas), CERO)
    return {"filas": filas, "toca": suma("toca"), "pagado": suma("pagado"), "falta": sum((max(f["falta"], CERO) for f in filas), CERO),
            "con_comision": bool(comisiones)}
