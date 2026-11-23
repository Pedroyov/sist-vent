"""Conciliación de cobros electrónicos (Yape, Plin, tarjeta, transferencia) por día y por método.

El sistema suma lo que se registró ese día con ese método —ventas vigentes, pagos de fiado y pagos de cuotas— y quien
concilia escribe lo que muestra el banco o la app. Si no cuadra, se revisan las operaciones y se marca cuál no llegó:
queda como faltante de quien la cobró (Reportes → Control). Funciona con o sin el módulo Caja.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from core.utils import dias

from .models import CERO, Conciliacion, MetodoPago, NoLlego

ELECTRONICOS = (MetodoPago.YAPE, MetodoPago.PLIN, MetodoPago.TARJETA, MetodoPago.TRANSFERENCIA)
DIAS_AVISO = 2      # el inicio avisa si un día con movimiento pasa más de esto sin conciliar
DIAS_REVISAR = 7    # ...mirando solo la última semana (así no salta todo el historial al empezar a usarla)
CENTIMO = Decimal("0.01")


class ConciliacionError(Exception):
    pass


def _fuentes():
    """(tipo, pagos vigentes, campo de fecha, campo de quien cobró, relaciones) de todo lo que entra por un método."""
    from clientes.models import Abono
    from cobranzas.models import Pago as PagoCuotas

    from .models import Pago, Venta

    return [
        (NoLlego.Tipo.VENTA, Pago.objects.filter(venta__estado=Venta.Estado.PAGADA), "venta__fecha", "venta__usuario", ("venta", "venta__usuario")),
        (NoLlego.Tipo.ABONO, Abono.objects.filter(anulado=False), "fecha", "usuario", ("cliente", "usuario")),
        (NoLlego.Tipo.CUOTA, PagoCuotas.objects.filter(anulado=False), "fecha", "usuario", ("cliente", "usuario")),
    ]


def metodos_visibles(con_movimiento=()):
    """Los electrónicos que acepta el negocio, más los que tuvieron movimiento aunque ya no se acepten."""
    from core.models import Ajustes

    aceptados = set(Ajustes.cargar().metodos_aceptados)
    return [m for m in ELECTRONICOS if m in aceptados or m in set(con_movimiento)]


def totales(desde, hasta):
    """{(día, método): {"total", "n"}} de lo registrado en el sistema por métodos electrónicos."""
    return cobros(desde, hasta, ELECTRONICOS)


def cobros(desde, hasta, metodos):
    """{(día, método): {"total", "n"}} de todo lo cobrado (ventas vigentes, pagos de fiado y de cuotas) con esos métodos.
    También lo usa el flujo de caja (reportes/flujo.py) para el efectivo."""
    tz = timezone.get_current_timezone()
    r = defaultdict(lambda: {"total": CERO, "n": 0})
    for _, qs, campo, _, _ in _fuentes():
        for f in (qs.filter(metodo__in=list(metodos), **dias(campo, desde, hasta)).annotate(dia=TruncDate(campo, tzinfo=tz))
                  .values("dia", "metodo").annotate(t=Sum("monto"), n=Count("id"))):
            x = r[(f["dia"], f["metodo"])]
            x["total"] = (x["total"] + f["t"]).quantize(CENTIMO)
            x["n"] += f["n"]
    return dict(r)


def resumen(desde, hasta):
    """Un día por fila (del más reciente al más antiguo), con cada método: lo del sistema y su conciliación si la hay.
    Solo días con movimiento o ya conciliados."""
    t = totales(desde, hasta)
    conc = {(c.fecha, c.metodo): c for c in Conciliacion.objects.filter(fecha__gte=desde, fecha__lte=hasta).select_related("usuario")
            .annotate(n_no_llego=Count("no_llegaron"))}
    metodos = metodos_visibles({m for _, m in t} | {m for _, m in conc})
    filas, dia = [], hasta
    while dia >= desde:
        celdas = []
        for m in metodos:
            s, c = t.get((dia, m)), conc.get((dia, m))
            if not s and not c:
                continue
            sistema = s["total"] if s else CERO
            estado = "pendiente" if c is None else ("ok" if c.diferencia == 0 else "diferencia")
            celdas.append({"metodo": m, "nombre": MetodoPago(m).label, "sistema": sistema, "n": s["n"] if s else 0, "conc": c,
                           "estado": estado, "cambio": bool(c and c.sistema != sistema)})
        if celdas:
            filas.append({"dia": dia, "metodos": celdas})
        dia -= timedelta(days=1)
    return filas


def operaciones(dia, metodo):
    """Cada cobro de ese día con ese método, en orden de hora, marcando los que no llegaron."""
    marcados = {(n.tipo, n.objeto_id): n for n in NoLlego.objects.filter(conciliacion__fecha=dia, conciliacion__metodo=metodo)}
    ops = []
    for tipo, qs, campo, _, rel in _fuentes():
        for p in qs.filter(metodo=metodo, **dias(campo, dia)).select_related(*rel):
            if tipo == NoLlego.Tipo.VENTA:
                v = p.venta
                d = {"fecha": v.fecha, "usuario": v.usuario, "descripcion": f"Venta {v.numero_str}", "url": reverse("ventas:ticket", args=[v.pk])}
            elif tipo == NoLlego.Tipo.ABONO:
                d = {"fecha": p.fecha, "usuario": p.usuario, "descripcion": f"Pago de fiado {p.numero} · {p.cliente.nombre}",
                     "url": reverse("clientes:detalle", args=[p.cliente_id])}
            else:
                d = {"fecha": p.fecha, "usuario": p.usuario, "descripcion": f"Cuotas {p.numero} · {p.cliente.nombre}",
                     "url": reverse("clientes:detalle", args=[p.cliente_id])}
            ops.append({"tipo": tipo, "id": p.pk, "monto": p.monto, "referencia": p.referencia, "no_llego": marcados.get((tipo, p.pk)), **d})
    ops.sort(key=lambda o: o["fecha"])
    return ops


def conciliar(dia, metodo, banco, usuario, nota=""):
    """Guarda (o corrige) lo que muestra el banco para ese día y método. La diferencia = banco − sistema."""
    if metodo not in ELECTRONICOS:
        raise ConciliacionError("Método no válido.")
    if dia > timezone.localdate():
        raise ConciliacionError("No se puede conciliar un día que todavía no llega.")
    try:
        banco = Decimal(str(banco).replace(",", ".")).quantize(CENTIMO)
    except Exception:
        raise ConciliacionError("Escribe el monto que muestra el banco.")
    if banco < 0:
        raise ConciliacionError("El monto no puede ser negativo.")
    from core.bitacora import anotar

    sistema = totales(dia, dia).get((dia, metodo), {}).get("total", CERO)
    nombre = MetodoPago(metodo).label
    with transaction.atomic():
        c = Conciliacion.objects.select_for_update().filter(fecha=dia, metodo=metodo).first()
        if c is None:
            try:
                with transaction.atomic():
                    c = Conciliacion.objects.create(fecha=dia, metodo=metodo, sistema=sistema, banco=banco, diferencia=banco - sistema,
                                                    nota=str(nota or "")[:200], usuario=usuario)
            except IntegrityError:
                raise ConciliacionError("Otra persona acaba de conciliar ese día. Vuelve a abrirlo.")
            if c.diferencia:
                anotar("conciliacion.diferencia", f"{nombre} del {dia:%d/%m/%Y}: el sistema dice S/ {sistema:.2f} y el banco S/ {banco:.2f}",
                       objeto=c, usuario=usuario, despues={"sistema": sistema, "banco": banco, "diferencia": c.diferencia})
            return c
        antes = {"sistema": c.sistema, "banco": c.banco, "diferencia": c.diferencia}
        c.sistema, c.banco, c.diferencia, c.usuario, c.creado = sistema, banco, banco - sistema, usuario, timezone.now()
        if nota:
            c.nota = str(nota)[:200]
        c.save()
        if antes["banco"] != banco or antes["sistema"] != sistema:
            anotar("conciliacion.cambiada", f"{nombre} del {dia:%d/%m/%Y}: banco S/ {antes['banco']:.2f} → S/ {banco:.2f}"
                   + (f" (el sistema pasó de S/ {antes['sistema']:.2f} a S/ {sistema:.2f})" if antes["sistema"] != sistema else ""),
                   objeto=c, usuario=usuario, antes=antes, despues={"sistema": sistema, "banco": banco, "diferencia": c.diferencia})
    return c


def marcar_no_llego(conciliacion, tipo, objeto_id, usuario):
    op = next((o for o in operaciones(conciliacion.fecha, conciliacion.metodo) if o["tipo"] == tipo and o["id"] == objeto_id), None)
    if op is None:
        raise ConciliacionError("Ese cobro no es de este día y método.")
    if op["no_llego"]:
        return op["no_llego"]
    from core.bitacora import anotar

    with transaction.atomic():
        n = NoLlego.objects.create(conciliacion=conciliacion, tipo=tipo, objeto_id=objeto_id, descripcion=op["descripcion"][:120],
                                   monto=op["monto"], cobro=op["usuario"], marcado_por=usuario)
        anotar("pago.no_llego", f"{conciliacion.get_metodo_display()} de S/ {op['monto']:.2f} ({op['descripcion']}, cobró "
               f"{op['usuario'].get_full_name() or op['usuario'].username}) no llegó al banco", objeto=conciliacion, usuario=usuario,
               despues={"tipo": tipo, "id": objeto_id, "monto": op["monto"], "referencia": op["referencia"]})
    return n


def quitar_no_llego(conciliacion, tipo, objeto_id, usuario):
    from core.bitacora import anotar

    with transaction.atomic():
        n = NoLlego.objects.select_for_update().filter(conciliacion=conciliacion, tipo=tipo, objeto_id=objeto_id).first()
        if n is None:
            return
        anotar("pago.no_llego_quitado", f"{n.descripcion} (S/ {n.monto:.2f}) vuelve a contar como recibido", objeto=conciliacion, usuario=usuario,
               antes={"tipo": tipo, "id": objeto_id, "monto": n.monto, "marcado_por": str(n.marcado_por)})
        n.delete()


def pendientes(hoy=None):
    """Para el inicio: por método, desde qué día hay movimiento sin conciliar (más de DIAS_AVISO días atrás)."""
    hoy = hoy or timezone.localdate()
    hasta = hoy - timedelta(days=DIAS_AVISO + 1)
    desde = hoy - timedelta(days=DIAS_REVISAR)
    if hasta < desde:
        return []
    t = totales(desde, hasta)
    hechos = set(Conciliacion.objects.filter(fecha__gte=desde, fecha__lte=hasta).values_list("fecha", "metodo"))
    falta = defaultdict(list)
    for (dia, m), x in t.items():
        if x["total"] and (dia, m) not in hechos:
            falta[m].append(dia)
    return [{"metodo": m, "nombre": MetodoPago(m).label, "desde": min(d), "dias": len(d)} for m, d in sorted(falta.items())]


def para_reportes(desde, hasta):
    """Diferencias de conciliación por método y lo que no llegó por cajero, en el periodo."""
    por_metodo = []
    for f in (Conciliacion.objects.filter(fecha__gte=desde, fecha__lte=hasta).values("metodo")
              .annotate(n=Count("id"), dif=Sum("diferencia"), sistema=Sum("sistema"), banco=Sum("banco")).order_by("metodo")):
        por_metodo.append({**f, "nombre": MetodoPago(f["metodo"]).label})
    por_cajero = []
    for f in (NoLlego.objects.filter(conciliacion__fecha__gte=desde, conciliacion__fecha__lte=hasta)
              .values("cobro__first_name", "cobro__last_name", "cobro__username").annotate(n=Count("id"), t=Sum("monto")).order_by("-t")):
        nombre = f"{f['cobro__first_name']} {f['cobro__last_name']}".strip() or f["cobro__username"] or "—"
        por_cajero.append({"etiqueta": nombre, "n": f["n"], "total": f["t"]})
    return {"por_metodo": por_metodo, "por_cajero": por_cajero, "hay": bool(por_metodo),
            "diferencia": sum((f["dif"] for f in por_metodo), CERO), "no_llego": sum((f["total"] for f in por_cajero), CERO)}
