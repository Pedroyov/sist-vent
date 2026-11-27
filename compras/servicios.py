"""Registrar, pagar y anular compras. Toda la lógica del módulo vive aquí; las vistas solo la llaman."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import CERO, Compra, CompraItem, Proveedor

C2 = Decimal("0.01")


class CompraError(Exception):
    pass


def _dec(valor, que):
    try:
        d = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, TypeError, ValueError):
        raise CompraError(f"{que}: no es un número válido.")
    if not d.is_finite():
        raise CompraError(f"{que}: no es un número válido.")
    return d


def _igv_pct():
    from facturacion.models import Config

    return Config.cargar().igv


def con_pagado(qs):
    """Agrega `_pagado` (pagos no anulados) a cada compra, sin una consulta por fila."""
    return qs.annotate(_pagado=Coalesce(Sum("pagos__monto", filter=Q(pagos__anulado=False)), Value(CERO),
                                        output_field=DecimalField(max_digits=12, decimal_places=2)))


def con_saldo():
    """Compras vigentes que todavía deben algo, las que vencen primero adelante."""
    from django.db.models import F

    return (con_pagado(Compra.objects.filter(anulada=False)).filter(total__gt=F("_pagado"))
            .select_related("proveedor").order_by(F("vence").asc(nulls_last=True), "fecha", "id"))


def _lineas(items):
    """[{"variante": id|None, "descripcion": "...", "cantidad": "2", "costo": "3.50"}] → líneas validadas."""
    from productos.models import Variante

    if not items:
        raise CompraError("Agrega al menos una línea.")
    if len(items) > 300:
        raise CompraError("Demasiadas líneas en una sola compra.")
    ids = [int(i["variante"]) for i in items if str(i.get("variante") or "").isdigit()]
    variantes = Variante.objects.select_related("producto").in_bulk(ids)
    lineas = []
    for it in items:
        vid = int(it["variante"]) if str(it.get("variante") or "").isdigit() else None
        v = variantes.get(vid) if vid else None
        if vid and v is None:
            raise CompraError("Uno de los productos ya no existe. Recarga la página.")
        if v is not None and not v.producto.maneja_stock:
            raise CompraError(f"«{v.nombre_completo}» no controla stock: regístralo como línea libre.")
        nombre = v.nombre_completo if v else " ".join(str(it.get("descripcion") or "").split())[:200]
        if not nombre:
            raise CompraError("Escribe qué es cada línea libre (ej.: «Bolsas», «Flete»).")
        cantidad = _dec(it.get("cantidad") or 0, f"Cantidad de {nombre}")
        costo = _dec(it.get("costo") or 0, f"Costo de {nombre}")
        if cantidad <= 0:
            raise CompraError(f"La cantidad de {nombre} debe ser mayor que cero.")
        if v is not None and not v.producto.fraccionable and cantidad != cantidad.to_integral_value():
            raise CompraError(f"{nombre} va por unidades enteras.")
        if costo < 0:
            raise CompraError(f"El costo de {nombre} no puede ser negativo.")
        lineas.append((v, nombre, cantidad, costo.quantize(Decimal("0.0001")), (cantidad * costo).quantize(C2)))
    return lineas


PROVEEDOR_VARIOS = "Proveedor varios"


def proveedor_varios():
    """El proveedor genérico de las compras sin proveedor registrado (mercado, ambulante). Se crea la primera vez."""
    p = Proveedor.objects.filter(nombre=PROVEEDOR_VARIOS, ruc="").order_by("id").first()
    return p or Proveedor.objects.create(nombre=PROVEEDOR_VARIOS, nota="Compras sin proveedor registrado (mercado, ambulantes).")


def registrar_compra(usuario, proveedor, items, documento=Compra.Documento.FACTURA, serie="", numero="", fecha=None,
                     credito=False, vence=None, pago=None, nota="", token=None):
    """Registra la compra en una sola transacción: cabecera, líneas, ingreso al kardex (costo promedio) y, si se paga al
    contado, el egreso de caja (`pago="caja"`, de la caja abierta de quien registra) o fuera de caja (`pago="fuera"`).
    Al crédito queda el saldo con su fecha de vencimiento (por defecto, fecha + plazo del proveedor)."""
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import CajaError, gasto_fuera_de_caja, movimiento
    from productos.models import MovimientoStock
    from productos.servicios import mover_stock

    if token:
        previa = Compra.objects.filter(token=token).first()
        if previa:
            return previa
    if credito and (proveedor is None or proveedor.nombre == PROVEEDOR_VARIOS):
        raise CompraError("Para dejarla por pagar (al crédito) elige el proveedor: a quién le debes.")
    if proveedor is None:  # compra en el mercado, a un ambulante…: va a «Proveedor varios» (como «Clientes varios»)
        proveedor = proveedor_varios()
    if documento not in Compra.Documento.values:
        raise CompraError("Documento no válido.")
    serie = "".join(str(serie or "").split()).upper()[:4]
    numero = "".join(str(numero or "").split()).lstrip("0")[:12] or ("0" if str(numero or "").strip() else "")
    hoy = timezone.localdate()
    fecha = fecha or hoy
    if fecha > hoy:
        raise CompraError("La fecha de la compra no puede ser futura.")
    lineas = _lineas(items)
    total = sum((l[4] for l in lineas), CERO)
    if total <= 0:
        raise CompraError("El total de la compra debe ser mayor que cero.")
    if credito:
        vence = vence or fecha + timedelta(days=proveedor.plazo or 30)
        if vence < fecha:
            raise CompraError("El vencimiento no puede ser antes de la fecha de la compra.")
        pago = None
    else:
        vence = None
        if pago not in ("caja", "fuera"):
            raise CompraError("Indica si se pagó de tu caja, fuera de caja o si queda al crédito.")
    base = igv = CERO
    if documento == Compra.Documento.FACTURA:
        base = (total / (1 + _igv_pct() / 100)).quantize(C2)
        igv = total - base
    if numero and Compra.objects.filter(proveedor=proveedor, documento=documento, serie=serie, numero=numero, anulada=False).exists():
        raise CompraError(f"Ya se registró {Compra.Documento(documento).label.lower()} {serie}-{numero} de {proveedor}.")
    try:
        with transaction.atomic():
            sesion = None
            if pago == "caja":
                sesion = SesionCaja.abierta_de(usuario)
                if sesion is None:
                    raise CompraError("Para pagar de tu caja, ábrela primero (o marca «fuera de caja»).")
            c = Compra.objects.create(proveedor=proveedor, documento=documento, serie=serie, numero=numero, fecha=fecha, vence=vence,
                                      base=base, igv=igv, total=total, nota=" ".join(str(nota or "").split())[:200],
                                      usuario=usuario, token=token or None)
            for v, nombre, cantidad, costo, subtotal in lineas:
                CompraItem.objects.create(compra=c, variante=v, descripcion=nombre, cantidad=cantidad, costo_unitario=costo,
                                          subtotal=subtotal, costo_antes=v.costo_efectivo if v is not None else None)
                if v is not None:
                    mover_stock(v, cantidad, MovimientoStock.Tipo.INGRESO, usuario, nota=f"Compra a {proveedor}"[:200],
                                costo_unitario=costo, referencia=c.referencia)
            concepto = f"{c.documento_str} · {proveedor}"
            try:
                if pago == "caja":
                    movimiento(sesion, MovimientoCaja.Tipo.EGRESO, total, concepto, usuario, MovimientoCaja.Categoria.PROVEEDOR, compra=c)
                elif pago == "fuera":
                    gasto_fuera_de_caja(total, concepto, usuario, MovimientoCaja.Categoria.PROVEEDOR, fecha, compra=c)
            except CajaError as e:
                raise CompraError(str(e))
    except IntegrityError:
        if token:
            previa = Compra.objects.filter(token=token).first()
            if previa:
                return previa
        raise
    return c


def pagar(compra, monto, usuario, origen="caja", fecha=None):
    """Un pago (total o a cuenta) de una compra. `origen`: "caja" (la caja abierta de quien paga) o "fuera"."""
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import CajaError, gasto_fuera_de_caja, movimiento

    monto = _dec(monto, "Monto").quantize(C2)
    if monto <= 0:
        raise CompraError("El monto debe ser mayor que cero.")
    if origen not in ("caja", "fuera"):
        raise CompraError("Indica de dónde sale el pago.")
    with transaction.atomic():
        c = Compra.objects.select_for_update().select_related("proveedor").get(pk=compra.pk)  # dos pagos a la vez no pasan del saldo
        if c.anulada:
            raise CompraError("Esa compra está anulada.")
        if monto > c.saldo:
            raise CompraError(f"Solo se debe S/ {c.saldo:.2f} de esa compra.")
        concepto = f"Pago {c.documento_str} · {c.proveedor}"
        try:
            if origen == "caja":
                sesion = SesionCaja.abierta_de(usuario)
                if sesion is None:
                    raise CompraError("Para pagar de tu caja, ábrela primero (o paga fuera de caja).")
                return movimiento(sesion, MovimientoCaja.Tipo.EGRESO, monto, concepto, usuario, MovimientoCaja.Categoria.PROVEEDOR,
                                  compra=c)
            return gasto_fuera_de_caja(monto, concepto, usuario, MovimientoCaja.Categoria.PROVEEDOR, fecha, compra=c)
        except CajaError as e:
            raise CompraError(str(e))


def pagar_proveedor(proveedor, monto, usuario, origen="caja", fecha=None):
    """Reparte un pago entre las compras que se le deben, de la más antigua a la más nueva. Devuelve los pagos hechos."""
    monto = _dec(monto, "Monto").quantize(C2)
    if monto <= 0:
        raise CompraError("El monto debe ser mayor que cero.")
    with transaction.atomic():
        # se bloquean primero (FOR UPDATE no va con sumas agrupadas) y el saldo se calcula por compra
        pendientes = list(Compra.objects.select_for_update().filter(proveedor=proveedor, anulada=False).order_by("fecha", "id"))
        pendientes = [c for c in pendientes if c.saldo > 0]
        deuda = sum((c.saldo for c in pendientes), CERO)
        if not pendientes:
            raise CompraError(f"No se le debe nada a {proveedor}.")
        if monto > deuda:
            raise CompraError(f"A {proveedor} solo se le debe S/ {deuda:.2f}.")
        pagos, resto = [], monto
        for c in pendientes:
            if resto <= 0:
                break
            parte = min(resto, c.saldo)
            pagos.append(pagar(c, parte, usuario, origen, fecha))
            resto -= parte
    return pagos


def anular_compra(compra, usuario, motivo):
    """Anula la compra: saca del stock lo que había sumado (kardex «Anulación de compra»). Los pagos fuera de caja se anulan
    antes (desde Gastos); los que salieron de una caja quedan en su cierre y el reembolso del proveedor se registra como
    ingreso en una caja abierta. El costo promedio no se recalcula hacia atrás."""
    from productos.models import MovimientoStock
    from productos.servicios import mover_stock

    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise CompraError("Indica el motivo.")
    with transaction.atomic():
        c = Compra.objects.select_for_update().get(pk=compra.pk)
        if c.anulada:
            raise CompraError("Esa compra ya estaba anulada.")
        if c.pagos.filter(anulado=False, sesion__isnull=True).exists():
            raise CompraError("Tiene pagos fuera de caja: anúlalos primero en Gastos.")
        for i in c.items.select_related("variante__producto").filter(variante__isnull=False):
            mover_stock(i.variante, -i.cantidad, MovimientoStock.Tipo.ANULACION_COMPRA, usuario, nota=f"Anulación: {motivo}"[:200],
                        referencia=c.referencia)
        c.anulada, c.anulada_en, c.anulada_por, c.motivo_anulacion = True, timezone.now(), usuario, motivo
        c.save(update_fields=["anulada", "anulada_en", "anulada_por", "motivo_anulacion"])
        from core.bitacora import anotar

        anotar("compra.anulada", f"Compra {c.documento_str} de {c.proveedor} por S/ {c.total:.2f} anulada: {motivo}", objeto=c,
               usuario=usuario)
    return c


def deudas_por_proveedor():
    """[{proveedor, deuda, vencido, compras, proxima}] de quienes se les debe algo, lo vencido primero."""
    hoy = timezone.localdate()
    por = {}
    for c in con_saldo():
        d = por.setdefault(c.proveedor_id, {"proveedor": c.proveedor, "deuda": CERO, "vencido": CERO, "compras": 0, "proxima": None})
        d["deuda"] += c.saldo
        d["compras"] += 1
        if c.vence and c.vence < hoy:
            d["vencido"] += c.saldo
        elif c.vence and (d["proxima"] is None or c.vence < d["proxima"]):
            d["proxima"] = c.vence
    return sorted(por.values(), key=lambda d: (-d["vencido"], d["proxima"] or hoy + timedelta(days=9999), -d["deuda"]))


def vencen_pronto(dias=7):
    """Compras con saldo que vencen dentro de `dias` (o ya vencieron)."""
    hoy = timezone.localdate()
    return [c for c in con_saldo().filter(vence__isnull=False, vence__lte=hoy + timedelta(days=dias))]


def ultima_compra(variante):
    return (CompraItem.objects.filter(variante=variante, compra__anulada=False).select_related("compra__proveedor")
            .order_by("-compra__fecha", "-id").first())


def ultima_de_producto(producto):
    """La última vez que se compró (cualquiera de sus variantes): fecha, proveedor y costo."""
    return (CompraItem.objects.filter(variante__producto=producto, compra__anulada=False).select_related("compra__proveedor", "variante")
            .order_by("-compra__fecha", "-id").first())


def por_proveedor(desde, hasta):
    """Lo comprado en el periodo por proveedor (sin anuladas), de mayor a menor."""
    filas = (Compra.objects.filter(anulada=False, fecha__gte=desde, fecha__lte=hasta).values("proveedor")
             .annotate(total=Sum("total"), n=Count("id")).order_by("-total"))
    nombres = {p.pk: p for p in Proveedor.objects.filter(pk__in=[f["proveedor"] for f in filas])}
    deudas = {d["proveedor"].pk: d for d in deudas_por_proveedor()}
    salida = [{"proveedor": nombres[f["proveedor"]], "total": f["total"], "n": f["n"],
               "deuda": deudas.get(f["proveedor"], {}).get("deuda", CERO)} for f in filas]
    deuda = sum((d["deuda"] for d in deudas.values()), CERO)
    vencido = sum((d["vencido"] for d in deudas.values()), CERO)
    return {"filas": salida, "total": sum((f["total"] for f in salida), CERO), "n": sum(f["n"] for f in salida),
            "deuda": deuda, "vencido": vencido}


def registro(desde, hasta):
    """Las compras del periodo para el Registro de compras del contador (también las anuladas, marcadas)."""
    return list(con_pagado(Compra.objects.filter(fecha__gte=desde, fecha__lte=hasta)).select_related("proveedor").order_by("fecha", "id"))


def reposicion():
    """Lo que llegó a su stock mínimo, agrupado por el proveedor al que se le compró la última vez (con la cantidad y el
    costo de esa compra, para pedir lo mismo). Lo que nunca se compró por el módulo va en un grupo sin proveedor."""
    from core.utils import enlace_whatsapp
    from productos.servicios import por_reponer

    variantes = list(por_reponer().select_related("producto").order_by("producto__nombre"))
    ultimas = {}
    for i in (CompraItem.objects.filter(variante__in=variantes, compra__anulada=False).select_related("compra__proveedor")
              .order_by("variante_id", "-compra__fecha", "-id")):
        ultimas.setdefault(i.variante_id, i)
    grupos = {}
    for v in variantes:
        u = ultimas.get(v.pk)
        p = u.compra.proveedor if u else None
        g = grupos.setdefault(p.pk if p else None, {"proveedor": p, "items": []})
        g["items"].append({"variante": v, "stock": v.stock, "minimo": v.producto.stock_minimo, "ultima": u})
    salida = sorted(grupos.values(), key=lambda g: (g["proveedor"] is None, str(g["proveedor"] or "")))
    for g in salida:
        if g["proveedor"] and g["proveedor"].telefono:
            lineas = "\n".join(f"- {x['variante'].nombre_completo}" + (f": {x['ultima'].cantidad.normalize():f}" if x["ultima"] else "")
                               for x in g["items"])
            g["whatsapp"] = enlace_whatsapp(g["proveedor"].telefono, f"Hola, quiero hacer un pedido:\n{lineas}")
    return salida


SUBIO = Decimal("1.01")  # menos de 1 % es redondeo, no una subida


def precios_a_revisar(compra):
    """Lo que subió de costo en esta compra, con el precio que mantendría la misma ganancia (redondeado hacia arriba a
    10 céntimos): [{"item", "variante", "nombre", "precio", "sugerido", "costo_antes", "costo"}]. Sin costo anterior
    no se sugiere nada, salvo que ya se venda por debajo del costo."""
    from decimal import ROUND_CEILING

    from productos.models import CambioPreciosItem

    # lo que ya se subió de precio después de esta compra no se vuelve a sugerir
    ya = set(CambioPreciosItem.objects.filter(cambio__fecha__gte=compra.creado, cambio__deshecho__isnull=True)
             .values_list("producto_id", flat=True))
    filas, vistos = [], set()
    for i in compra.items.select_related("variante__producto").filter(variante__isnull=False):
        v = i.variante
        if v.pk in vistos or not v.producto.activo or v.producto_id in ya:
            continue
        precio = v.precio_venta
        costo = Decimal(i.costo_unitario)
        if i.costo_antes and costo > i.costo_antes * SUBIO:
            nuevo = precio * costo / i.costo_antes
        elif costo >= precio and precio > 0:
            nuevo = costo * Decimal("1.25")  # vende a pérdida y no hay con qué comparar: 25 % sobre el costo
        else:
            continue
        nuevo = (nuevo / Decimal("0.10")).to_integral_value(ROUND_CEILING) * Decimal("0.10")
        if nuevo <= precio:
            continue
        vistos.add(v.pk)
        filas.append({"item": i, "variante": v, "nombre": str(v), "precio": precio, "sugerido": nuevo.quantize(Decimal("0.01")),
                      "costo_antes": i.costo_antes, "costo": costo.quantize(Decimal("0.01"))})
    return filas
