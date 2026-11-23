"""Abrir, mover y cerrar la caja. El efectivo esperado se calcula siempre igual: aquí."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from core.utils import dias

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


def bloquear_abierta(sesion):
    """Dentro de una transacción: bloquea la caja y confirma que siga abierta. Así un cobro no cae en un turno que se
    está cerrando en ese mismo instante (su efectivo no saldría en ningún cierre)."""
    if sesion is None:
        return None
    s = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
    if not s.abierta:
        raise CajaError("Esa caja se acaba de cerrar. Abre tu caja de nuevo para continuar.")
    return s


def movimiento(sesion, tipo, monto, concepto, usuario, categoria=MovimientoCaja.Categoria.OTRO, automatico=False, persona=None,
               compra=None):
    with transaction.atomic():
        bloquear_abierta(sesion)
        return MovimientoCaja.objects.create(sesion=sesion, tipo=tipo, monto=monto, concepto=concepto[:150], categoria=categoria,
                                             usuario=usuario, automatico=automatico, persona=_persona(categoria, persona),
                                             compra=compra)


def devolver_efectivo(sesion_origen, monto, usuario, concepto):
    """Al anular un cobro en efectivo de un turno ya cerrado, el dinero sale de la caja abierta de quien anula.
    Sin caja abierta no se permite: el efectivo saldría sin dejar rastro. Con su caja aún abierta, el cobro anulado
    simplemente deja de sumar y no hace falta nada."""
    if not monto or sesion_origen is None or sesion_origen.abierta:
        return None
    actual = SesionCaja.abierta_de(usuario)
    if actual is None:
        raise CajaError(f"Para anular hay que devolver S/ {monto:.2f} en efectivo de un turno ya cerrado: abre tu caja primero, "
                        "así la salida queda registrada.")
    return movimiento(actual, MovimientoCaja.Tipo.EGRESO, monto, concepto, usuario, MovimientoCaja.Categoria.DEVOLUCION,
                      automatico=True)


def gasto_fuera_de_caja(monto, concepto, usuario, categoria, fecha=None, persona=None, compra=None):
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
                                         categoria=categoria, usuario=usuario, fecha=momento, persona=_persona(categoria, persona),
                                         compra=compra)


def anular_gasto(gasto, usuario, motivo):
    """Anula un gasto fuera de caja: deja de contar en los reportes, pero queda registrado con quién, cuándo y por qué."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CajaError("Indica el motivo.")
    with transaction.atomic():
        m = MovimientoCaja.objects.select_for_update().get(pk=gasto.pk)
        if m.sesion_id is not None:
            raise CajaError("Lo que salió de una caja queda en su cierre; para corregirlo, registra un ingreso en una caja abierta.")
        if m.anulado:
            raise CajaError("Ese gasto ya estaba anulado.")
        m.anulado, m.anulado_en, m.anulado_por, m.motivo_anulacion = True, timezone.now(), usuario, motivo
        m.save(update_fields=["anulado", "anulado_en", "anulado_por", "motivo_anulacion"])
        from core.bitacora import anotar

        anotar("gasto.anulado", f"Gasto «{m.concepto}» de S/ {m.monto:.2f} anulado: {motivo}", objeto=m, usuario=usuario)
    return m


def _persona(categoria, persona):
    return persona if categoria == MovimientoCaja.Categoria.PERSONAL else None


def gastos(desde, hasta):
    """Gastos del periodo por motivo (de las cajas y fuera de caja). No son gastos: los retiros del dueño ni lo que el
    sistema devolvió al anular un cobro (la venta anulada ya no suma). Las compras a proveedores van aparte en la ganancia:
    el costo de lo vendido ya se resta en la ganancia de las ventas."""
    C = MovimientoCaja.Categoria
    qs = (MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, automatico=False, anulado=False, **dias("fecha", desde, hasta))
          .exclude(categoria=C.RETIRO))
    datos = {r["categoria"]: r for r in qs.values("categoria").annotate(total=Sum("monto"), n=Count("id"))}
    filas = [{"categoria": c.value, "etiqueta": c.label.split(" (")[0], "total": datos[c.value]["total"], "n": datos[c.value]["n"]}
             for c in C if c.value in datos]
    libres = compras_sin_producto(desde, hasta)
    if libres["n"]:
        filas.append({"categoria": COMPRAS_SIN_PRODUCTO, "etiqueta": "Compras sin producto (insumos, fletes)", **libres})
    filas.sort(key=lambda f: -f["total"])
    total = sum((f["total"] for f in filas), CERO)
    maximo = max((f["total"] for f in filas), default=0) or 1
    for f in filas:
        f["pct"] = round(float(f["total"]) / float(maximo) * 100, 1)
    proveedores = datos.get(C.PROVEEDOR, {}).get("total") or CERO
    retiros = sum(retiros_por_dia(desde, hasta).values(), CERO)
    return {"filas": filas, "total": total, "proveedores": proveedores, "operativos": total - proveedores, "retiros": retiros,
            "fuera": qs.filter(sesion__isnull=True).aggregate(t=Sum("monto"))["t"] or CERO}


def retiros_por_dia(desde, hasta):
    """{día: monto} de lo que se llevó el dueño: egresos «Retiro» y lo retirado al cerrar cada caja (contado − lo que se dejó).
    Única definición de «retiros» (Gastos y el flujo de caja la usan)."""
    from django.db.models.functions import TruncDate

    tz = timezone.get_current_timezone()
    r = defaultdict(lambda: CERO)
    for f in (MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, categoria=MovimientoCaja.Categoria.RETIRO, anulado=False,
                                            **dias("fecha", desde, hasta))
              .annotate(dia=TruncDate("fecha", tzinfo=tz)).values("dia").annotate(t=Sum("monto"))):
        r[f["dia"]] += f["t"]
    for f in (SesionCaja.objects.filter(estado=SesionCaja.Estado.CERRADA, queda__isnull=False, **dias("cerrada_en", desde, hasta))
              .annotate(dia=TruncDate("cerrada_en", tzinfo=tz)).values("dia").annotate(t=Sum(F("contado") - F("queda")))):
        r[f["dia"]] += f["t"] or CERO
    return dict(r)


COMPRAS_SIN_PRODUCTO = "CSP"  # no es un motivo de caja: son las líneas libres de las compras registradas


def compras_sin_producto(desde, hasta):
    """Líneas libres de las compras del periodo (insumos, fletes, bolsas): no son mercadería, así que son gasto del periodo
    en que se compraron, se paguen cuando se paguen. Sus pagos (motivo «Pago a proveedor») no se vuelven a contar."""
    from compras.models import CompraItem

    r = (CompraItem.objects.filter(variante__isnull=True, compra__anulada=False, compra__fecha__gte=desde, compra__fecha__lte=hasta)
         .aggregate(total=Sum("subtotal"), n=Count("compra", distinct=True)))
    return {"total": r["total"] or CERO, "n": r["n"] or 0}


def sencillo_anterior(usuario):
    """El cierre del que viene el sencillo del cajón: con una sola caja, el último cierre de cualquiera; con varias,
    el último del mismo cajero (no se sabe aún en cuál va a abrir)."""
    from .models import PuntoCaja

    cerradas = SesionCaja.objects.filter(estado=SesionCaja.Estado.CERRADA)
    if PuntoCaja.objects.filter(activo=True).count() > 1:
        cerradas = cerradas.filter(usuario=usuario)
    ultima = cerradas.order_by("-cerrada_en").first()
    if ultima is None or ultima.contado is None:
        return None, None
    return ultima, (ultima.queda if ultima.queda is not None else ultima.contado)


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
        "otros_medios": sum((m["total"] for m in metodos if m["codigo"] not in (MetodoPago.EFECTIVO, MetodoPago.CREDITO, MetodoPago.SALDO)), CERO)
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


TOLERANCIA_RECONTEO = Decimal("1.00")


def no_cuadra(sesion, contado):
    """Para el cierre ciego: True si lo contado se aleja de lo esperado más que la tolerancia (se pide volver a contar
    sin decir cuánto falta ni sobra)."""
    return abs(contado - calcular(sesion)["esperado"]) > TOLERANCIA_RECONTEO


def cerrar(sesion, contado, usuario, conteo=None, nota="", queda=None, primer_conteo=None):
    """Cierra el turno. `queda` = el sencillo que se deja en el cajón para el siguiente turno (lo demás se retira);
    sin indicarlo, se entiende que todo lo contado se queda. `primer_conteo`: el que no cuadró, si se volvió a contar."""
    queda = contado if queda is None else queda
    if queda < 0 or queda > contado:
        raise CajaError(f"Lo que dejas en el cajón no puede ser más de lo contado (S/ {contado:.2f}).")
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
        s.queda = queda
        s.diferencia = contado - r["esperado"]
        s.conteo = conteo or {}
        s.nota_cierre = nota[:300]
        s.primer_conteo = primer_conteo if primer_conteo is not None and primer_conteo != contado else None
        s.resumen = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "metodos"}
        s.resumen["metodos"] = [{**m, "total": str(m["total"])} for m in r["metodos"]]
        s.save()
        from core.bitacora import anotar

        if s.diferencia:
            anotar("caja.diferencia", f"Caja {s.numero} de {s.usuario} cerrada con {'sobrante' if s.diferencia > 0 else 'faltante'} "
                   f"de S/ {abs(s.diferencia):.2f}" + (f" (volvió a contar; la primera vez contó S/ {s.primer_conteo:.2f})" if s.primer_conteo is not None else ""),
                   objeto=s, usuario=usuario,
                   despues={"esperado": s.esperado, "contado": s.contado, "diferencia": s.diferencia, "primer_conteo": s.primer_conteo})
        if usuario.pk != s.usuario_id:
            anotar("caja.cierre_ajeno", f"Caja {s.numero} de {s.usuario} cerrada por {usuario}", objeto=s, usuario=usuario)
    return s


def corregir_conteo(sesion, contado, usuario, motivo):
    """Una caja cerrada no se reabre (se podría vender en un día ya cerrado y cambiarían los reportes). Si se contó mal
    (un sobre que no se contó, un billete pegado), Administración corrige lo contado con motivo: cambia la diferencia,
    se guarda el conteo original y queda en la bitácora. Lo que se dejó en el cajón no cambia."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CajaError("Indica el motivo de la corrección.")
    if contado is None or contado < 0:
        raise CajaError("Indica cuánto se contó.")
    with transaction.atomic():
        s = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
        if s.abierta:
            raise CajaError("La caja todavía está abierta: corrige el conteo al cerrarla.")
        if contado < (s.queda or CERO):
            raise CajaError(f"No puede ser menos de lo que se dejó en el cajón (S/ {s.queda:.2f}).")
        if contado == s.contado:
            raise CajaError("Es el mismo monto que ya estaba.")
        antes = {"contado": s.contado, "diferencia": s.diferencia}
        if s.contado_original is None:
            s.contado_original = s.contado
        s.contado = contado
        s.diferencia = contado - s.esperado
        s.corregido_en, s.corregido_por, s.motivo_correccion = timezone.now(), usuario, motivo
        s.save(update_fields=["contado", "diferencia", "contado_original", "corregido_en", "corregido_por", "motivo_correccion"])
        from core.bitacora import anotar

        anotar("caja.correccion", f"Caja {s.numero} de {s.usuario}: contado S/ {antes['contado']:.2f} → S/ {contado:.2f}: {motivo}",
               objeto=s, usuario=usuario, antes=antes, despues={"contado": s.contado, "diferencia": s.diferencia})
    return s


def por_que_no_reabrir(sesion):
    """"" si Administración puede reabrir esta caja; si no, el motivo. Solo la última caja del cajero, sin otra abierta
    después, y el mismo día que se cerró: así no se vende en un turno ya entregado ni cambian días ya revisados."""
    if sesion.abierta:
        return "La caja ya está abierta."
    if timezone.localtime(sesion.cerrada_en).date() != timezone.localdate():
        return "Solo se reabre el mismo día que se cerró. Para un día anterior, corrige el conteo."
    if SesionCaja.objects.filter(usuario_id=sesion.usuario_id, pk__gt=sesion.pk).exists():
        return "Después de esta caja ya se abrió otra: corrige el conteo o agrega la salida olvidada en lugar de reabrirla."
    # un cajón, un turno abierto a la vez: si otra persona ya tomó el mismo cajón, no se reabre
    mismo_cajon = SesionCaja.objects.filter(punto_id=sesion.punto_id).exclude(pk=sesion.pk)
    if mismo_cajon.filter(pk__gt=sesion.pk).exists() or mismo_cajon.filter(estado=SesionCaja.Estado.ABIERTA).exists():
        return ("Después de esta caja ya se abrió otra en el mismo cajón. Si faltó una salida, agrégala como salida olvidada; "
                "para seguir vendiendo, abre una caja nueva cuando el cajón esté libre.")
    return ""


def salida_olvidada(sesion, monto, concepto, usuario, categoria, persona=None):
    """Una salida de dinero que pasó en el turno pero no se anotó (pago a proveedor, gasto, adelanto). Se agrega a la caja ya
    cerrada sin reabrirla: lo que debía haber baja y la diferencia se recalcula. Lo contado no cambia. Va a la bitácora."""
    concepto = " ".join(str(concepto or "").split())[:150]
    if not concepto:
        raise CajaError("Describe la salida.")
    if not monto or monto <= 0:
        raise CajaError("El monto debe ser mayor que cero.")
    with transaction.atomic():
        s = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
        if s.abierta:
            raise CajaError("La caja está abierta: registra la salida normalmente.")
        m = MovimientoCaja.objects.create(sesion=s, tipo=MovimientoCaja.Tipo.EGRESO, monto=monto, concepto=concepto, categoria=categoria,
                                          usuario=usuario, persona=_persona(categoria, persona), fecha=s.cerrada_en, despues_del_cierre=True)
        antes = {"esperado": s.esperado, "diferencia": s.diferencia}
        s.esperado -= monto
        s.diferencia = s.contado - s.esperado
        r = dict(s.resumen or {})
        for k, signo in (("egresos", 1), ("esperado", -1)):
            if k in r:
                r[k] = str(Decimal(r[k]) + signo * monto)
        s.resumen = r
        s.save(update_fields=["esperado", "diferencia", "resumen"])
        from core.bitacora import anotar

        anotar("caja.salida_olvidada", f"Caja {s.numero} de {s.usuario}: salida olvidada de S/ {monto:.2f} ({m.motivo}: {concepto}). "
               f"{'Ahora cuadra' if s.diferencia == 0 else ('Sobrante' if s.diferencia > 0 else 'Faltante') + f' de S/ {abs(s.diferencia):.2f}'}",
               objeto=s, usuario=usuario, antes=antes, despues={"esperado": s.esperado, "diferencia": s.diferencia, "monto": monto})
    return s


def reabrir(sesion, usuario, motivo):
    """Vuelve a abrir una caja cerrada por error (o porque faltó anotar un gasto). El cierre anterior queda en `reaperturas`
    y en la bitácora. Lo que se retiró al cerrar ya salió del cajón: se anota como retiro para que el nuevo cierre cuadre."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CajaError("Indica por qué se reabre la caja.")
    with transaction.atomic():
        s = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
        if error := por_que_no_reabrir(s):
            raise CajaError(error)
        anterior = {
            "cerrada_en": s.cerrada_en.isoformat(), "cerrada_por": str(s.cerrada_por) if s.cerrada_por else "",
            "esperado": str(s.esperado), "contado": str(s.contado), "diferencia": str(s.diferencia), "queda": str(s.queda),
            "primer_conteo": str(s.primer_conteo) if s.primer_conteo is not None else None,
            "contado_original": str(s.contado_original) if s.contado_original is not None else None,
            "nota_cierre": s.nota_cierre, "reabierta_en": timezone.now().isoformat(), "reabierta_por": str(usuario), "motivo": motivo,
        }
        retirado = s.retirado or CERO
        if retirado > 0:
            MovimientoCaja.objects.create(sesion=s, tipo=MovimientoCaja.Tipo.EGRESO, monto=retirado, categoria=MovimientoCaja.Categoria.RETIRO,
                                          concepto="Retirado al cerrar (antes de reabrir)", usuario=usuario, automatico=True,
                                          fecha=s.cerrada_en)
        s.reaperturas = [*(s.reaperturas or []), anterior]
        s.estado = SesionCaja.Estado.ABIERTA
        s.cerrada_en = s.cerrada_por = s.esperado = s.contado = s.diferencia = s.queda = None
        s.primer_conteo = s.contado_original = s.corregido_en = s.corregido_por = None
        s.conteo, s.resumen, s.nota_cierre, s.motivo_correccion = {}, {}, "", ""
        try:
            with transaction.atomic():
                s.save()
        except IntegrityError:
            raise CajaError(f"{s.usuario} ya tiene otra caja abierta.")
        from core.bitacora import anotar

        anotar("caja.reabierta", f"Caja {s.numero} de {s.usuario} reabierta: {motivo}", objeto=s, usuario=usuario,
               antes={k: anterior[k] for k in ("esperado", "contado", "diferencia", "queda")}, despues={"retiro_anotado": retirado})
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
