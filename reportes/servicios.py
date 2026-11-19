"""Cálculos de los reportes. Todo sale de las ventas, cajas, mesas y stock ya registrados (no hay tablas propias)."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate, TruncMonth
from django.utils import timezone

CERO = Decimal("0")
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
DINERO = DecimalField(max_digits=14, decimal_places=2)


def c(valor):
    return Decimal(valor or 0).quantize(Decimal("0.01"))


# --- Periodo ---------------------------------------------------------------------

ATAJOS = [("hoy", "Hoy"), ("ayer", "Ayer"), ("7d", "7 días"), ("30d", "30 días"), ("mes", "Este mes"), ("mes_pasado", "Mes pasado")]


def periodo(request, defecto="7d"):
    """(desde, hasta, clave del atajo). Por defecto, los últimos 7 días (o «Este mes» con defecto="mes")."""
    hoy = timezone.localdate()
    p = request.GET.get("p", "")
    if p == "hoy":
        return hoy, hoy, p
    if p == "ayer":
        return hoy - timedelta(days=1), hoy - timedelta(days=1), p
    if p == "30d":
        return hoy - timedelta(days=29), hoy, p
    if p == "mes":
        return hoy.replace(day=1), hoy, p
    if p == "mes_pasado":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin, p
    try:
        desde = date.fromisoformat(request.GET.get("desde", ""))
        hasta = date.fromisoformat(request.GET.get("hasta", ""))
        if hasta < desde:
            desde, hasta = hasta, desde
        if (hasta - desde).days > 366 * 3:
            desde = hasta - timedelta(days=366 * 3)
        return desde, hasta, ""
    except ValueError:
        if defecto == "mes":
            return hoy.replace(day=1), hoy, "mes"
        return hoy - timedelta(days=6), hoy, "7d"


def anterior(desde, hasta):
    dias = (hasta - desde).days + 1
    return desde - timedelta(days=dias), desde - timedelta(days=1)


# --- Ventas ----------------------------------------------------------------------

def ventas(desde, hasta):
    from ventas.models import Venta

    return Venta.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta, estado=Venta.Estado.PAGADA)


def resumen(desde, hasta):
    from ventas.models import Venta
    from ventas.servicios import resumen as resumen_ventas

    todas = Venta.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta)
    r = resumen_ventas(todas)
    r["anuladas_monto"] = c(todas.filter(estado=Venta.Estado.ANULADA).aggregate(t=Sum("total"))["t"])
    d0, d1 = anterior(desde, hasta)
    previo = resumen_ventas(Venta.objects.filter(fecha__date__gte=d0, fecha__date__lte=d1))
    r["anterior"] = {"desde": d0, "hasta": d1, "total": previo["total"], "n": previo["n"]}
    r["variacion"] = ((r["total"] - previo["total"]) / previo["total"] * 100).quantize(Decimal("0.1")) if previo["total"] else None
    dias = (hasta - desde).days + 1
    r["por_dia"] = c(r["total"] / dias)
    return r


def _con_barras(filas, campo="total"):
    maximo = max((f[campo] for f in filas), default=0) or 1
    for f in filas:
        f["pct"] = round(float(f[campo]) / float(maximo) * 100, 1)
    return filas


def por_fecha(desde, hasta):
    """Por día (o por mes si el periodo pasa de 3 meses), incluyendo los días sin ventas."""
    mensual = (hasta - desde).days > 92
    trunc = TruncMonth("fecha") if mensual else TruncDate("fecha")
    datos = {(r["f"].date() if hasattr(r["f"], "hour") else r["f"]): r
             for r in ventas(desde, hasta).annotate(f=trunc).values("f").annotate(total=Sum("total"), n=Count("id"))}
    filas = []
    if mensual:
        d = desde.replace(day=1)
        while d <= hasta:
            r = datos.get(d, {})
            filas.append({"etiqueta": f"{MESES[d.month - 1]} {d.year}", "fecha": d, "total": c(r.get("total")), "n": r.get("n", 0)})
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        d = desde
        while d <= hasta:
            r = datos.get(d, {})
            filas.append({"etiqueta": f"{DIAS[d.weekday()][:3]} {d:%d/%m}", "fecha": d, "total": c(r.get("total")), "n": r.get("n", 0)})
            d += timedelta(days=1)
    return _con_barras(filas), mensual


def por_hora(desde, hasta):
    datos = {r["h"]: r for r in ventas(desde, hasta).annotate(h=ExtractHour("fecha")).values("h").annotate(total=Sum("total"), n=Count("id"))}
    if not datos:
        return []
    filas = [{"etiqueta": f"{h:02d}:00", "total": c(datos.get(h, {}).get("total")), "n": datos.get(h, {}).get("n", 0)}
             for h in range(min(datos), max(datos) + 1)]
    return _con_barras(filas)


def por_dia_semana(desde, hasta):
    # ExtractWeekDay: 1 = domingo … 7 = sábado
    datos = {r["d"]: r for r in ventas(desde, hasta).annotate(d=ExtractWeekDay("fecha")).values("d").annotate(total=Sum("total"), n=Count("id"))}
    filas = []
    for i, nombre in enumerate(DIAS):
        r = datos.get((i + 1) % 7 + 1, {})
        filas.append({"etiqueta": nombre, "total": c(r.get("total")), "n": r.get("n", 0)})
    return _con_barras(filas)


def productos(desde, hasta, limite=None):
    """Por producto: cantidad, total cobrado, costo y ganancia (antes del descuento general de la venta)."""
    from ventas.models import VentaItem

    costo = ExpressionWrapper(F("cantidad") * F("costo_unitario"), output_field=DINERO)
    qs = (VentaItem.objects.filter(venta__in=ventas(desde, hasta))
          .values("variante__producto_id", "variante__producto__nombre", "variante__producto__categoria__nombre",
                  "variante__producto__unidad", "variante__producto__tipo")
          .annotate(r_cant=Sum("cantidad"), r_total=Sum("subtotal"), r_costo=Sum(costo), n_ventas=Count("venta", distinct=True))
          .order_by("-r_total"))
    filas = []
    total = CERO
    for r in qs:
        t = c(r["r_total"])
        total += t
        filas.append({"id": r["variante__producto_id"], "nombre": r["variante__producto__nombre"],
                      "categoria": r["variante__producto__categoria__nombre"] or "Sin categoría", "cantidad": r["r_cant"].normalize(),
                      "total": t, "costo": c(r["r_costo"]) if r["r_costo"] is not None else None,
                      "ganancia": t - c(r["r_costo"]) if r["r_costo"] is not None else None, "n_ventas": r["n_ventas"],
                      "servicio": r["variante__producto__tipo"] == "S"})
    for f in filas:
        f["participacion"] = (f["total"] / total * 100).quantize(Decimal("0.1")) if total else CERO
    filas = _con_barras(filas)
    return filas[:limite] if limite else filas


def opciones(desde, hasta):
    """Opciones y adicionales elegidos: cuántas veces y cuánto se cobró por ellos."""
    from ventas.models import VentaItem

    agrupado = defaultdict(lambda: {"veces": Decimal(0), "ingreso": CERO})
    for item in VentaItem.objects.filter(venta__in=ventas(desde, hasta)).exclude(opciones=[]).values("opciones", "cantidad"):
        for o in item["opciones"] or []:
            if o.get("c"):  # lo que trae un combo no es una opción elegida
                continue
            g = agrupado[(o.get("g", ""), o.get("n", ""))]
            g["veces"] += item["cantidad"]
            g["ingreso"] += Decimal(o.get("p") or 0) * item["cantidad"]
    filas = [{"grupo": k[0], "etiqueta": k[1], "veces": v["veces"].normalize(), "ingreso": c(v["ingreso"]), "total": v["veces"]}
             for k, v in agrupado.items()]
    filas.sort(key=lambda f: (-f["ingreso"], -f["veces"]))
    return _con_barras(filas)


def categorias(desde, hasta):
    agrupado = defaultdict(lambda: {"total": CERO, "cantidad": Decimal(0), "ganancia": CERO, "productos": 0})
    for p in productos(desde, hasta):
        g = agrupado[p["categoria"]]
        g["total"] += p["total"]
        g["cantidad"] += p["cantidad"]
        g["productos"] += 1
        if p["ganancia"] is not None:
            g["ganancia"] += p["ganancia"]
    total = sum((g["total"] for g in agrupado.values()), CERO)
    filas = [{"etiqueta": k, **v, "participacion": (v["total"] / total * 100).quantize(Decimal("0.1")) if total else CERO}
             for k, v in agrupado.items()]
    return _con_barras(sorted(filas, key=lambda f: -f["total"]))


def sin_ventas(desde, hasta, limite=30):
    """Productos activos que no se vendieron en el periodo (candidatos a promoción o a dejar de comprar)."""
    from productos.models import Producto
    from ventas.models import VentaItem

    vendidos = VentaItem.objects.filter(venta__in=ventas(desde, hasta)).values("variante__producto_id")
    return list(Producto.objects.filter(activo=True, tipo="P").exclude(pk__in=vendidos).select_related("categoria").order_by("nombre")[:limite])


def por_usuario(desde, hasta, campo="usuario"):
    """Ventas por quien cobró (usuario) o por el mozo que atendió (atendio)."""
    qs = ventas(desde, hasta).exclude(**{f"{campo}__isnull": True}).values(campo, f"{campo}__first_name", f"{campo}__last_name", f"{campo}__username")
    filas = []
    for r in qs.annotate(total=Sum("total"), n=Count("id"), propinas=Sum("propina")).order_by("-total"):
        nombre = f"{r[f'{campo}__first_name']} {r[f'{campo}__last_name']}".strip() or r[f"{campo}__username"]
        filas.append({"etiqueta": nombre, "total": c(r["total"]), "n": r["n"], "promedio": c(r["total"] / r["n"]) if r["n"] else CERO,
                      "propinas": c(r["propinas"])})
    return _con_barras(filas)


# --- Restaurante ------------------------------------------------------------------

def mesas(desde, hasta):
    from mesas.models import Cuenta, ItemCuenta

    cuentas = list(Cuenta.objects.filter(estado=Cuenta.Estado.COBRADA, abierta_en__date__gte=desde, abierta_en__date__lte=hasta)
                   .prefetch_related("items"))
    con_mesa = [x for x in cuentas if x.mesa_id]
    personas = sum(x.personas for x in con_mesa)
    consumo = sum((i.subtotal for x in con_mesa for i in x.items.all() if not i.anulado), CERO)
    consumo_contado = sum((i.subtotal for x in con_mesa if x.personas for i in x.items.all() if not i.anulado), CERO)  # mesas con personas indicadas
    minutos = [int((x.cerrada_en - x.abierta_en).total_seconds() // 60) for x in con_mesa if x.cerrada_en]
    quitados = list(ItemCuenta.objects.filter(anulado=True, enviado_en__isnull=False, cuenta__abierta_en__date__gte=desde,
                                              cuenta__abierta_en__date__lte=hasta)
                    .select_related("cuenta__mesa", "cuenta__mozo", "anulado_por").order_by("-creado"))
    por_mesa = defaultdict(lambda: {"cuentas": 0, "total": CERO})
    for x in con_mesa:
        m = por_mesa[x.mesa.nombre if x.mesa else "—"]
        m["cuentas"] += 1
        m["total"] += sum((i.subtotal for i in x.items.all() if not i.anulado), CERO)
    deliverys = [x for x in cuentas if x.tipo == Cuenta.Tipo.DELIVERY]
    por_repartidor = defaultdict(lambda: {"total": 0, "minutos": []})
    for x in deliverys:
        r = por_repartidor[x.repartidor or "Sin indicar"]
        r["total"] += 1
        if x.entregado_en:
            r["minutos"].append(int((x.entregado_en - x.abierta_en).total_seconds() // 60))
    entregas = [m for r in por_repartidor.values() for m in r["minutos"]]
    delivery = {
        "n": len(deliverys),
        "envios": c(sum((i.subtotal for x in deliverys for i in x.items.all() if i.es_envio and not i.anulado), CERO)),
        "consumo": c(sum((i.subtotal for x in deliverys for i in x.items.all() if not i.es_envio and not i.anulado), CERO)),
        "minutos_promedio": round(sum(entregas) / len(entregas)) if entregas else None,
        "repartidores": _con_barras(sorted([{"etiqueta": k, "total": v["total"],
                                             "minutos": round(sum(v["minutos"]) / len(v["minutos"])) if v["minutos"] else None}
                                            for k, v in por_repartidor.items()], key=lambda f: -f["total"])),
    }
    return {
        "delivery": delivery,
        "atenciones": len(con_mesa), "para_llevar": len(cuentas) - len(con_mesa) - len(deliverys), "personas": personas,
        "por_persona": c(consumo_contado / personas) if personas else CERO, "consumo": c(consumo),
        "minutos_promedio": round(sum(minutos) / len(minutos)) if minutos else None,
        "quitados": quitados, "quitados_valor": c(sum((i.subtotal for i in quitados), CERO)),
        "por_mesa": _con_barras(sorted([{"etiqueta": k, **v} for k, v in por_mesa.items()], key=lambda f: -f["total"])),
    }


# --- Inventario --------------------------------------------------------------------

def inventario(desde, hasta):
    from productos.models import MovimientoStock, Variante
    from productos.views import por_reponer

    valor, sin_costo, unidades = CERO, 0, 0
    for v in Variante.objects.filter(activa=True, producto__activo=True, producto__maneja_stock=True, stock__gt=0).select_related("producto"):
        unidades += 1
        if v.costo_efectivo is None:
            sin_costo += 1
        else:
            valor += v.stock * v.costo_efectivo
    salidas = []
    merma = CERO
    for m in (MovimientoStock.objects.filter(tipo=MovimientoStock.Tipo.SALIDA, fecha__date__gte=desde, fecha__date__lte=hasta)
              .select_related("variante__producto", "usuario").order_by("-fecha")):
        costo = m.variante.costo_efectivo
        m.valor = c(-m.cantidad * costo) if costo is not None else None
        merma += m.valor or CERO
        salidas.append(m)
    ajustes = MovimientoStock.objects.filter(tipo=MovimientoStock.Tipo.AJUSTE, fecha__date__gte=desde, fecha__date__lte=hasta)
    return {"valor": c(valor), "con_stock": unidades, "sin_costo": sin_costo,
            "por_reponer": por_reponer().values("producto_id").distinct().count(),
            "salidas": salidas[:30], "merma": c(merma), "ajustes": ajustes.count()}


# --- Clientes y caja --------------------------------------------------------------

def deudores(limite=20):
    from clientes.models import Abono
    from clientes.servicios import con_saldo, total_por_cobrar, vencido
    from ventas.models import MetodoPago, Pago, Venta

    hoy = timezone.localdate()
    filas = []
    for cl in con_saldo().filter(fiado__gt=F("abonado")).order_by("-fiado")[:200]:
        saldo = c(cl.fiado - cl.abonado)
        ultimo_pago = Abono.objects.filter(cliente=cl, anulado=False).order_by("-fecha").values_list("fecha", flat=True).first()
        ultimo_fiado = (Pago.objects.filter(venta__cliente=cl, metodo=MetodoPago.CREDITO, venta__estado=Venta.Estado.PAGADA)
                        .order_by("-venta__fecha").values_list("venta__fecha", flat=True).first())
        desde = ultimo_pago or (Pago.objects.filter(venta__cliente=cl, metodo=MetodoPago.CREDITO, venta__estado=Venta.Estado.PAGADA)
                                .order_by("venta__fecha").values_list("venta__fecha", flat=True).first())
        dias = (hoy - timezone.localtime(desde).date()).days if desde else None
        filas.append({"cliente": cl, "saldo": saldo, "ultimo_pago": ultimo_pago, "ultimo_fiado": ultimo_fiado, "dias": dias,
                      "vencido": vencido(cl),
                      "excede": bool(cl.limite_credito and saldo > cl.limite_credito)})
    filas.sort(key=lambda f: -f["saldo"])
    return {"total": total_por_cobrar(), "filas": filas[:limite], "n": len(filas),
            "antiguos": sum(1 for f in filas if f["dias"] is not None and f["dias"] > 30),
            "vencido": sum((f["vencido"] for f in filas), CERO)}


def cajas(desde, hasta):
    from caja.models import SesionCaja

    cerradas = list(SesionCaja.objects.filter(estado=SesionCaja.Estado.CERRADA, cerrada_en__date__gte=desde, cerrada_en__date__lte=hasta)
                    .select_related("usuario"))
    por_cajero = defaultdict(lambda: {"cajas": 0, "faltante": CERO, "sobrante": CERO, "con_diferencia": 0})
    for s in cerradas:
        p = por_cajero[s.usuario.get_full_name() or s.usuario.username]
        p["cajas"] += 1
        if s.diferencia:
            p["con_diferencia"] += 1
            if s.diferencia < 0:
                p["faltante"] += s.diferencia
            else:
                p["sobrante"] += s.diferencia
    filas = sorted([{"etiqueta": k, **v} for k, v in por_cajero.items()], key=lambda f: f["faltante"])
    return {"filas": filas, "n": len(cerradas), "faltante": sum((f["faltante"] for f in filas), CERO),
            "sobrante": sum((f["sobrante"] for f in filas), CERO)}


def anuladas(desde, hasta):
    from ventas.models import Venta

    return list(Venta.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta, estado=Venta.Estado.ANULADA)
                .select_related("usuario", "anulada_por").order_by("-fecha")[:30])


def cortesias_descuentos(desde, hasta):
    """Lo que se regaló o rebajó en ventas vigentes: con motivo, quién atendió y quién autorizó."""
    from ventas.models import Venta, VentaItem

    vigentes = dict(venta__fecha__date__gte=desde, venta__fecha__date__lte=hasta, venta__estado=Venta.Estado.PAGADA)
    cortesias = list(VentaItem.objects.filter(cortesia=True, **vigentes)
                     .select_related("venta", "venta__usuario", "venta__atendio", "cortesia_por").order_by("-venta__fecha"))
    for i in cortesias:
        i.valor = c(i.precio_lista * i.cantidad)
    descuentos = list(Venta.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta, estado=Venta.Estado.PAGADA, descuento__gt=0)
                      .select_related("usuario", "atendio", "descuento_por").order_by("-fecha"))
    motivos = defaultdict(lambda: {"veces": 0, "valor": CERO})
    for i in cortesias:
        m = motivos[i.cortesia_motivo or "Sin motivo"]
        m["veces"] += 1
        m["valor"] += i.valor
    return {"cortesias": cortesias, "descuentos": descuentos,
            "valor_cortesias": sum((i.valor for i in cortesias), CERO),
            "valor_descuentos": c(sum((v.descuento for v in descuentos), CERO)),
            "motivos": sorted([{"etiqueta": k, **v} for k, v in motivos.items()], key=lambda f: -f["valor"])}
