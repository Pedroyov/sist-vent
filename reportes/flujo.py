"""Dinero del día (flujo de caja): cuánto entró, cuánto salió y dónde quedó, día por día.

No guarda nada: junta lo que ya registran ventas, pagos de fiado y cuotas (ventas.conciliacion.cobros), las cajas
(MovimientoCaja, SesionCaja), los retiros (caja.servicios.retiros_por_dia) y la conciliación. El fiado vendido no es
dinero: sale aparte y entra el día que se cobra.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.utils import dias

CERO = Decimal("0")


def por_dia(desde, hasta):
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import retiros_por_dia
    from ventas.conciliacion import ELECTRONICOS, cobros, metodos_visibles
    from ventas.models import Conciliacion, MetodoPago, Pago, Venta

    tz = timezone.get_current_timezone()
    efectivo = cobros(desde, hasta, [MetodoPago.EFECTIVO])
    electronicos = cobros(desde, hasta, ELECTRONICOS)
    metodos = metodos_visibles({m for _, m in electronicos})

    def por_fecha(qs, campo, valor="monto"):
        return {f["dia"]: f["t"] or CERO for f in qs.filter(**dias(campo, desde, hasta)).annotate(dia=TruncDate(campo, tzinfo=tz))
                .values("dia").annotate(t=Sum(valor))}

    mov = MovimientoCaja.objects.filter(anulado=False)
    ingresos = por_fecha(mov.filter(tipo=MovimientoCaja.Tipo.INGRESO), "fecha")
    egresos = mov.filter(tipo=MovimientoCaja.Tipo.EGRESO).exclude(categoria=MovimientoCaja.Categoria.RETIRO)
    salio_cajas = por_fecha(egresos.filter(sesion__isnull=False), "fecha")
    salio_fuera = por_fecha(egresos.filter(sesion__isnull=True), "fecha")
    retiros = retiros_por_dia(desde, hasta)
    fiado = por_fecha(Pago.objects.filter(venta__estado=Venta.Estado.PAGADA, metodo=MetodoPago.CREDITO), "venta__fecha")
    cerradas = list(SesionCaja.objects.filter(estado=SesionCaja.Estado.CERRADA, **dias("cerrada_en", desde, hasta))
                    .only("cerrada_en", "punto_id", "usuario_id", "queda", "diferencia").order_by("cerrada_en"))
    dif_caja, queda = defaultdict(lambda: CERO), defaultdict(dict)
    for s in cerradas:
        d = timezone.localtime(s.cerrada_en).date()
        dif_caja[d] += s.diferencia or CERO
        # lo que quedó en cada cajón al final del día: la última caja cerrada de ese cajón (sin puntos: de cada cajero)
        queda[d][s.punto_id or f"u{s.usuario_id}"] = s.queda or CERO
    conc = defaultdict(lambda: {"dif": CERO, "hechos": set()})
    for c in Conciliacion.objects.filter(fecha__gte=desde, fecha__lte=hasta):
        conc[c.fecha]["dif"] += c.diferencia
        conc[c.fecha]["hechos"].add(c.metodo)

    filas, dia = [], hasta
    while dia >= desde:
        ef = efectivo.get((dia, MetodoPago.EFECTIVO), {}).get("total", CERO)
        por_metodo = [{"metodo": m, "nombre": MetodoPago(m).label, "total": electronicos.get((dia, m), {}).get("total", CERO),
                       "conciliado": m in conc[dia]["hechos"] if dia in conc else False} for m in metodos]
        elec = sum((x["total"] for x in por_metodo), CERO)
        f = {
            "dia": dia, "efectivo": ef, "metodos": por_metodo, "electronico": elec, "ingresos": ingresos.get(dia, CERO),
            "salio_cajas": salio_cajas.get(dia, CERO), "salio_fuera": salio_fuera.get(dia, CERO), "retirado": retiros.get(dia, CERO),
            "quedo": sum(queda[dia].values(), CERO) if dia in queda else None, "dif_caja": dif_caja.get(dia, CERO),
            "dif_conciliacion": conc[dia]["dif"] if dia in conc else CERO, "fiado": fiado.get(dia, CERO),
            "sin_conciliar": [x["nombre"] for x in por_metodo if x["total"] and not x["conciliado"]],
        }
        f["entro"] = f["efectivo"] + f["electronico"] + f["ingresos"]
        f["salio"] = f["salio_cajas"] + f["salio_fuera"]
        f["neto"] = f["entro"] - f["salio"]
        f["hay"] = any(f[k] for k in ("entro", "salio", "retirado", "fiado", "dif_caja")) or f["quedo"] is not None
        if f["hay"]:
            filas.append(f)
        dia -= timedelta(days=1)
    claves = ("efectivo", "electronico", "ingresos", "entro", "salio_cajas", "salio_fuera", "salio", "neto", "retirado", "dif_caja",
              "dif_conciliacion", "fiado")
    total = {k: sum((f[k] for f in filas), CERO) for k in claves}
    total["metodos"] = [{"nombre": MetodoPago(m).label, "total": sum((x["total"] for f in filas for x in f["metodos"] if x["metodo"] == m), CERO)}
                        for m in metodos]
    return {"filas": filas, "total": total, "metodos": [MetodoPago(m).label for m in metodos]}
