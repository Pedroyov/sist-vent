"""Abrir, mover y cerrar la caja. El efectivo esperado se calcula siempre igual: aquí."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import CERO, DENOMINACIONES, MovimientoCaja, SesionCaja


class CajaError(Exception):
    pass


def caja_activa():
    from core.permisos import modulos_activos

    return "caja" in modulos_activos()


def sesion_para_vender(usuario):
    """Caja abierta de quien cobra. Si el módulo está activo y es obligatoria, sin caja no se vende."""
    if not caja_activa():
        return None
    sesion = SesionCaja.abierta_de(usuario)
    if sesion is None:
        from core.models import Ajustes

        if not Ajustes.cargar().vender_sin_caja:
            raise CajaError("Abre tu caja antes de cobrar (menú Caja).")
    return sesion


def abrir(usuario, monto_inicial, nota="", punto=None):
    from .models import PuntoCaja

    activos = PuntoCaja.objects.filter(activo=True)
    if punto is None and activos.count() == 1:
        punto = activos.first()
    if punto is None and activos.exists():
        raise CajaError("Elige en qué caja estás.")
    if punto is not None and not punto.activo:
        raise CajaError("Esa caja está desactivada.")
    try:
        with transaction.atomic():
            return SesionCaja.objects.create(usuario=usuario, monto_inicial=monto_inicial, nota_apertura=nota[:200], punto=punto)
    except IntegrityError:
        raise CajaError("Ya tienes una caja abierta.")


def movimiento(sesion, tipo, monto, concepto, usuario, categoria=MovimientoCaja.Categoria.OTRO, automatico=False, persona=None):
    if not sesion.abierta:
        raise CajaError("La caja ya está cerrada.")
    return MovimientoCaja.objects.create(sesion=sesion, tipo=tipo, monto=monto, concepto=concepto[:150], categoria=categoria,
                                         usuario=usuario, automatico=automatico, persona=_persona(categoria, persona))


def gasto_fuera_de_caja(monto, concepto, usuario, categoria, fecha=None, persona=None):
    """Un gasto que no salió del cajón (transferencia, Yape, dinero del dueño): cuenta en los reportes, no en el cuadre de caja."""
    C = MovimientoCaja.Categoria
    if categoria == C.RETIRO:
        raise CajaError("Un retiro del dueño solo tiene sentido saliendo de una caja.")
    momento = timezone.now()
    if fecha is not None:
        if fecha > timezone.localdate():
            raise CajaError("La fecha no puede ser futura.")
        if fecha != timezone.localdate():  # un día pasado: al mediodía, para que no cambie de día por la zona horaria
            momento = timezone.make_aware(datetime(fecha.year, fecha.month, fecha.day, 12, 0))
    return MovimientoCaja.objects.create(sesion=None, tipo=MovimientoCaja.Tipo.EGRESO, monto=monto, concepto=concepto[:150],
                                         categoria=categoria, usuario=usuario, fecha=momento, persona=_persona(categoria, persona))


def _persona(categoria, persona):
    return persona if categoria == MovimientoCaja.Categoria.PERSONAL else None


def gastos(desde, hasta):
    """Gastos del periodo por motivo (de las cajas y fuera de caja). No son gastos: los retiros del dueño ni lo que el
    sistema devolvió al anular un cobro (la venta anulada ya no suma). Las compras a proveedores van aparte en la ganancia:
    el costo de lo vendido ya se resta en la ganancia de las ventas."""
    C = MovimientoCaja.Categoria
    qs = (MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, automatico=False, fecha__date__gte=desde, fecha__date__lte=hasta)
          .exclude(categoria=C.RETIRO))
    datos = {r["categoria"]: r for r in qs.values("categoria").annotate(total=Sum("monto"), n=Count("id"))}
    filas = [{"categoria": c.value, "etiqueta": c.label.split(" (")[0], "total": datos[c.value]["total"], "n": datos[c.value]["n"]}
             for c in C if c.value in datos]
    filas.sort(key=lambda f: -f["total"])
    total = sum((f["total"] for f in filas), CERO)
    maximo = max((f["total"] for f in filas), default=0) or 1
    for f in filas:
        f["pct"] = round(float(f["total"]) / float(maximo) * 100, 1)
    proveedores = datos.get(C.PROVEEDOR, {}).get("total") or CERO
    retiros = (MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, categoria=C.RETIRO, fecha__date__gte=desde,
                                             fecha__date__lte=hasta).aggregate(t=Sum("monto"))["t"] or CERO)
    return {"filas": filas, "total": total, "proveedores": proveedores, "operativos": total - proveedores, "retiros": retiros,
            "fuera": qs.filter(sesion__isnull=True).aggregate(t=Sum("monto"))["t"] or CERO}


def calcular(sesion):
    """Resumen del turno. El efectivo esperado = inicial + efectivo de ventas, pagos de deudas y de cuotas + ingresos − egresos."""
    from ventas.models import MetodoPago, Pago, Venta

    ventas = Venta.objects.filter(sesion_caja=sesion, estado=Venta.Estado.PAGADA)
    v = ventas.aggregate(n=Count("id"), total=Sum("total"), propinas=Sum("propina"))
    nombres = dict(MetodoPago.choices)
    metodos = []
    efectivo_ventas = CERO
    for m in Pago.objects.filter(venta__in=ventas).values("metodo").annotate(total=Sum("monto"), n=Count("venta", distinct=True)).order_by("-total"):
        metodos.append({"codigo": m["metodo"], "metodo": nombres.get(m["metodo"], m["metodo"]), "total": m["total"], "n": m["n"]})
        if m["metodo"] == MetodoPago.EFECTIVO:
            efectivo_ventas = m["total"]
    from clientes.models import Abono

    abonos = {a["metodo"]: a["t"] for a in Abono.objects.filter(sesion_caja=sesion, anulado=False).values("metodo").annotate(t=Sum("monto"))}
    abonos_efectivo = abonos.get(MetodoPago.EFECTIVO, CERO)
    from cobranzas.models import Pago as PagoCuotas

    cuotas = {p["metodo"]: p["t"] for p in PagoCuotas.objects.filter(sesion_caja=sesion, anulado=False).values("metodo").annotate(t=Sum("monto"))}
    cuotas_efectivo = cuotas.get(MetodoPago.EFECTIVO, CERO)
    movs = sesion.movimientos.values("tipo").annotate(t=Sum("monto"))
    ingresos = sum((m["t"] for m in movs if m["tipo"] == MovimientoCaja.Tipo.INGRESO), CERO)
    egresos = sum((m["t"] for m in movs if m["tipo"] == MovimientoCaja.Tipo.EGRESO), CERO)
    resultado = {
        "inicial": sesion.monto_inicial, "n_ventas": v["n"] or 0, "total_ventas": v["total"] or CERO,
        "propinas": v["propinas"] or CERO, "metodos": metodos, "efectivo_ventas": efectivo_ventas,
        "otros_medios": sum((m["total"] for m in metodos if m["codigo"] not in (MetodoPago.EFECTIVO, MetodoPago.CREDITO)), CERO)
                        + sum((t for k, t in abonos.items() if k != MetodoPago.EFECTIVO), CERO)
                        + sum((t for k, t in cuotas.items() if k != MetodoPago.EFECTIVO), CERO),
        "fiado": sum((m["total"] for m in metodos if m["codigo"] == MetodoPago.CREDITO), CERO),
        "abonos": sum(abonos.values(), CERO), "abonos_efectivo": abonos_efectivo,
        "cuotas": sum(cuotas.values(), CERO), "cuotas_efectivo": cuotas_efectivo,
        "ingresos": ingresos, "egresos": egresos,
        "esperado": sesion.monto_inicial + efectivo_ventas + abonos_efectivo + cuotas_efectivo + ingresos - egresos,
        "anuladas": Venta.objects.filter(sesion_caja=sesion, estado=Venta.Estado.ANULADA).count(),
    }
    # Las sumas de la base de datos pueden traer decimales de más (357.2000000): todo a céntimos
    for clave, valor in resultado.items():
        if isinstance(valor, Decimal):
            resultado[clave] = _c(valor)
    for m in resultado["metodos"]:
        m["total"] = _c(m["total"])
    return resultado


def _c(valor):
    return Decimal(valor).quantize(Decimal("0.01"))


def total_conteo(conteo):
    """{"200": 1, "0.50": 3} -> 201.50 (ignora lo que no sea una denominación válida)."""
    total = CERO
    limpio = {}
    for d in DENOMINACIONES:
        try:
            n = int(conteo.get(d) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            limpio[d] = n
            total += Decimal(d) * n
    return total, limpio


def cerrar(sesion, contado, usuario, conteo=None, nota=""):
    with transaction.atomic():
        s = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
        if not s.abierta:
            raise CajaError("Esta caja ya estaba cerrada.")
        r = calcular(s)
        s.estado = SesionCaja.Estado.CERRADA
        s.cerrada_en = timezone.now()
        s.cerrada_por = usuario
        s.esperado = r["esperado"]
        s.contado = contado
        s.diferencia = contado - r["esperado"]
        s.conteo = conteo or {}
        s.nota_cierre = nota[:300]
        s.resumen = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "metodos"}
        s.resumen["metodos"] = [{**m, "total": str(m["total"])} for m in r["metodos"]]
        s.save()
    return s


def resumen_guardado(sesion):
    """Para una caja cerrada: el resumen tal como quedó al cerrar (con números Decimal)."""
    r = dict(sesion.resumen or {})
    for k, v in list(r.items()):
        if isinstance(v, str):
            try:
                r[k] = Decimal(v)
            except InvalidOperation:
                pass
    r["metodos"] = [{**m, "total": Decimal(m["total"])} for m in r.get("metodos", [])]
    return r
