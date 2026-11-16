"""Clientes, fiado y pagos de deudas."""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .documentos import adivinar_tipo, validar
from .models import CERO, Abono, Cliente


class ClienteError(Exception):
    pass


def modulo_activo():
    from core.permisos import modulos_activos

    return "clientes" in modulos_activos()


def con_saldo(qs=None):
    """Clientes con el saldo calculado en la base de datos (para listas y totales)."""
    from ventas.models import MetodoPago, Pago, Venta

    qs = qs if qs is not None else Cliente.objects.all()
    dec = DecimalField(max_digits=14, decimal_places=2)
    fiado = (Pago.objects.filter(venta__cliente=OuterRef("pk"), venta__estado=Venta.Estado.PAGADA, metodo=MetodoPago.CREDITO)
             .values("venta__cliente").annotate(t=Sum("monto")).values("t"))
    abonos = Abono.objects.filter(cliente=OuterRef("pk"), anulado=False).values("cliente").annotate(t=Sum("monto")).values("t")
    return qs.annotate(fiado=Coalesce(Subquery(fiado, output_field=dec), Value(CERO), output_field=dec),
                       abonado=Coalesce(Subquery(abonos, output_field=dec), Value(CERO), output_field=dec))


def total_por_cobrar():
    total = CERO
    for c in con_saldo(Cliente.objects.all()).values("fiado", "abonado"):
        total += c["fiado"] - c["abonado"]
    return total.quantize(Decimal("0.01"))


def resolver_cliente(cliente_id=None, nombre="", documento="", crear=True):
    """El cliente de una venta: el elegido de la lista, o uno que se encuentra/crea por su DNI/RUC o por su nombre."""
    if cliente_id:
        c = Cliente.objects.filter(pk=cliente_id, activo=True).first()
        if c is None:
            raise ClienteError("Ese cliente ya no existe o está desactivado.")
        return c
    nombre = " ".join(str(nombre or "").split())[:150]
    tipo = adivinar_tipo(documento)
    if tipo:
        numero, error = validar(tipo, documento)
        if error:
            raise ClienteError(error)
        c = Cliente.objects.filter(tipo_documento=tipo, numero_documento=numero).first()
        if c or not crear:
            return c
        if not nombre:
            raise ClienteError("Escribe el nombre del cliente junto con su DNI/RUC.")
        try:
            with transaction.atomic():
                return Cliente.objects.create(tipo_documento=tipo, numero_documento=numero, nombre=nombre)
        except IntegrityError:
            return Cliente.objects.get(tipo_documento=tipo, numero_documento=numero)
    if str(documento or "").strip():
        raise ClienteError("El documento debe ser un DNI (8 dígitos) o un RUC (11 dígitos).")
    if nombre:
        c = Cliente.objects.filter(nombre__iexact=nombre, numero_documento="").first()
        if c or not crear:
            return c
        return Cliente.objects.create(tipo_documento=Cliente.TipoDocumento.SIN, nombre=nombre)
    return None


INCOBRABLE = "INC"  # «método» de un Abono que no es dinero: deuda que el negocio da por perdida


def deudas(cliente, hoy=None):
    """Cuenta corriente: cada venta al fiado con lo que falta pagar. Los pagos se aplican primero a lo más antiguo.
    Si la venta tiene factura al crédito, sus cuotas dicen qué parte ya venció."""
    from datetime import date

    from ventas.models import MetodoPago, Pago, Venta

    hoy = hoy or timezone.localdate()
    por_venta = {}
    for p in (Pago.objects.filter(venta__cliente=cliente, metodo=MetodoPago.CREDITO, venta__estado=Venta.Estado.PAGADA)
              .select_related("venta").order_by("venta__fecha", "venta_id")):
        por_venta.setdefault(p.venta_id, {"venta": p.venta, "monto": CERO})["monto"] += p.monto
    comprobantes = {}
    try:
        from facturacion.models import Comprobante

        for c in (Comprobante.objects.filter(venta_id__in=list(por_venta)).exclude(tipo=Comprobante.Tipo.NOTA_CREDITO)
                  .exclude(estado=Comprobante.Estado.RECHAZADO)):
            comprobantes[c.venta_id] = c
    except LookupError:
        pass
    disponible = cliente.total_abonado
    filas = []
    for vid, d in por_venta.items():
        pagado = min(disponible, d["monto"])
        disponible -= pagado
        c = comprobantes.get(vid)
        cuotas = c.cuotas if c and c.al_credito else []
        vencido, atraso, cubre, vence = CERO, 0, pagado, None
        for q in cuotas:
            monto, fecha = Decimal(q["monto"]), date.fromisoformat(q["fecha"])
            falta = max(CERO, monto - cubre)
            cubre = max(CERO, cubre - monto)
            if falta and vence is None:
                vence = fecha
            if falta and fecha < hoy:
                vencido += falta
                atraso = max(atraso, (hoy - fecha).days)
        filas.append({**d, "pagado": pagado, "pendiente": d["monto"] - pagado, "comprobante": c, "vence": vence,
                      "vencido": vencido, "dias_atraso": atraso})
    return filas


def vencido(cliente):
    return sum((f["vencido"] for f in deudas(cliente)), CERO)


def validar_fiado(cliente, monto, puede_fiar, puede_exceder):
    if not monto:
        return
    if not modulo_activo():
        raise ClienteError("El fiado no está activado.")
    if not puede_fiar:
        raise ClienteError("No tienes permiso para vender al fiado.")
    if cliente is None:
        raise ClienteError("Para fiar, elige o escribe el cliente.")
    if cliente.limite_credito and not puede_exceder:
        saldo = cliente.saldo
        if saldo + monto > cliente.limite_credito:
            raise ClienteError(f"{cliente.nombre} ya debe S/ {saldo:.2f} y su límite es S/ {cliente.limite_credito:.2f}. "
                               f"Puede fiársele hasta S/ {max(CERO, cliente.limite_credito - saldo):.2f}.")
    if not puede_exceder:
        atrasado = vencido(cliente)
        if atrasado:
            raise ClienteError(f"{cliente.nombre} tiene S/ {atrasado:.2f} vencido (facturas al crédito sin pagar). "
                               "No se le puede dar más crédito sin autorización.")


def registrar_abono(cliente, monto, metodo, usuario, nota="", referencia=""):
    from caja.servicios import CajaError, sesion_para_vender
    from ventas.models import MetodoPago

    try:
        monto = Decimal(str(monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise ClienteError("Monto no válido.")
    if monto <= 0:
        raise ClienteError("El monto debe ser mayor que cero.")
    if metodo not in MetodoPago.values or metodo == MetodoPago.CREDITO:
        raise ClienteError("Método de pago no válido.")
    try:
        sesion = sesion_para_vender(usuario)
    except CajaError as e:
        raise ClienteError(str(e))
    with transaction.atomic():
        Cliente.objects.select_for_update().get(pk=cliente.pk)  # evita dos pagos a la vez sobre la misma deuda
        saldo = cliente.saldo
        if monto > saldo:
            raise ClienteError(f"{cliente.nombre} solo debe S/ {saldo:.2f}.")
        return Abono.objects.create(cliente=cliente, monto=monto, metodo=metodo, usuario=usuario, sesion_caja=sesion,
                                    nota=str(nota or "")[:200], referencia=str(referencia or "")[:60])


def marcar_incobrable(cliente, monto, motivo, usuario):
    """El negocio da por perdida (toda o parte de) la deuda: deja de salir como pendiente, sin mover la caja.
    Lo que hace el contador con esa pérdida es aparte."""
    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise ClienteError("Indica el motivo.")
    try:
        monto = Decimal(str(monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise ClienteError("Monto no válido.")
    with transaction.atomic():
        Cliente.objects.select_for_update().get(pk=cliente.pk)
        saldo = cliente.saldo
        if monto <= 0 or monto > saldo:
            raise ClienteError(f"El monto tiene que ser mayor que cero y hasta S/ {saldo:.2f}.")
        return Abono.objects.create(cliente=cliente, monto=monto, metodo=INCOBRABLE, usuario=usuario, nota=f"Incobrable: {motivo}"[:200])


def anular_abono(abono, usuario, motivo):
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import movimiento
    from ventas.models import MetodoPago

    motivo = " ".join(str(motivo or "").split())[:200]
    if not motivo:
        raise ClienteError("Indica el motivo.")
    with transaction.atomic():
        a = Abono.objects.select_for_update().select_related("sesion_caja").get(pk=abono.pk)
        if a.anulado:
            raise ClienteError("Ese pago ya estaba anulado.")
        # Si su caja ya cerró, el efectivo devuelto sale de la caja abierta de quien anula
        if a.metodo == MetodoPago.EFECTIVO and a.sesion_caja_id and not a.sesion_caja.abierta:
            actual = SesionCaja.abierta_de(usuario)
            if actual:
                movimiento(actual, MovimientoCaja.Tipo.EGRESO, a.monto, f"Anulación del pago {a.numero} de {a.cliente}: {motivo}",
                           usuario, MovimientoCaja.Categoria.DEVOLUCION, automatico=True)
        a.anulado, a.anulado_en, a.anulado_por, a.motivo_anulacion = True, timezone.now(), usuario, motivo
        a.save(update_fields=["anulado", "anulado_en", "anulado_por", "motivo_anulacion"])
    return a


def estado_de_cuenta(cliente, limite=200):
    """Movimientos en orden: ventas al fiado (+) y pagos (−), con el saldo acumulado."""
    from ventas.models import MetodoPago, Pago, Venta

    movs = []
    for p in (Pago.objects.filter(venta__cliente=cliente, metodo=MetodoPago.CREDITO, venta__estado=Venta.Estado.PAGADA)
              .select_related("venta")):
        movs.append({"fecha": p.venta.fecha, "tipo": "fiado", "detalle": f"Venta {p.venta.numero_str}", "monto": p.monto,
                     "venta": p.venta})
    for a in cliente.abonos.filter(anulado=False):
        movs.append({"fecha": a.fecha, "tipo": "pago", "detalle": f"Pago {a.numero} · {a.get_metodo_display()}", "monto": -a.monto,
                     "abono": a})
    movs.sort(key=lambda m: m["fecha"])
    saldo = CERO
    for m in movs:
        saldo += m["monto"]
        m["saldo"] = saldo
    return list(reversed(movs))[:limite]
