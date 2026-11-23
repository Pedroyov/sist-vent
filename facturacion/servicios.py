"""Emitir, enviar y anular comprobantes electrónicos.

Uso desde una venta (punto de venta o mesas):
    sol = solicitud(datos.get("comprobante"))       # None = nota de venta
    revisar_antes(sol, credito)                       # datos del cliente, antes de registrar la venta
    with transaction.atomic():
        venta = registrar_venta(...)
        comp = crear(venta, sol, usuario)             # numera y arma; si algo falla, la venta tampoco se guarda
    enviar_seguro(comp)                               # fuera de la transacción: si no hay internet, queda pendiente
"""
import logging
from datetime import date as date_cls, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .conectores import ErrorConexion, conector
from .models import Comprobante, Config, Serie

log = logging.getLogger(__name__)
C2 = Decimal("0.01")
LIMITE_BOLETA_SIN_DNI = Decimal("700")
UNIDADES = {"KG": "KGM", "LT": "LTR", "MT": "MTR", "SRV": "ZZ"}
# Plazo para que SUNAT (u OSE) reciba boletas, facturas y sus notas: hasta el 3.er día calendario siguiente a la emisión
# (R.S. 000003-2023/SUNAT). Pasado ese día, el comprobante pierde validez.
PLAZO_SUNAT_DIAS = 3
POR_ENVIAR = [Comprobante.Estado.PENDIENTE, Comprobante.Estado.ENVIADO]


class ComprobanteError(Exception):
    pass


def activo():
    from core.permisos import modulos_activos

    return "facturacion" in modulos_activos()


def _r(x, q=C2):
    return Decimal(x).quantize(q, rounding=ROUND_HALF_UP)


# --- Datos del cliente -----------------------------------------------------------------

def solicitud(datos):
    """{"tipo": "B"|"F"|"N", "doc", "nombre", "direccion"} -> dict limpio, o None si es nota de venta."""
    if not isinstance(datos, dict) or not activo():
        return None
    tipo = str(datos.get("tipo") or "").upper()
    if tipo not in ("B", "F"):
        return None
    doc = "".join(ch for ch in str(datos.get("doc") or "") if ch.isalnum()).upper()[:15]
    from datetime import date

    try:
        vence = date.fromisoformat(str(datos.get("vence") or "")) if datos.get("vence") else None
    except ValueError:
        vence = "mal"
    try:
        cuotas = max(1, min(int(datos.get("cuotas") or 1), 12))
    except (TypeError, ValueError):
        cuotas = 1
    return {"tipo": tipo, "doc": doc, "nombre": " ".join(str(datos.get("nombre") or "").split())[:150],
            "direccion": " ".join(str(datos.get("direccion") or "").split())[:200], "vence": vence, "cuotas": cuotas}


def tipo_documento(doc):
    """El código de SUNAT según el número: 8 dígitos DNI (1), 11 dígitos RUC (6), otro carné de extranjería (4)."""
    if not doc:
        return "-"
    if doc.isdigit() and len(doc) == 8:
        return "1"
    if doc.isdigit() and len(doc) == 11:
        return "6"
    return "4"


def preparar(datos):
    """Desde el JSON del cobro: (solicitud, al crédito). Revisa los datos antes de registrar la venta."""
    sol = solicitud(datos.get("comprobante"))
    credito = any(isinstance(p, dict) and p.get("metodo") == "CRE" for p in datos.get("pagos") or [])
    revisar_antes(sol, credito)
    return sol


def revisar_antes(sol, credito=False):
    """Lo que se puede revisar antes de vender (para no registrar una venta que no se podrá facturar)."""
    if not sol:
        return
    from clientes.documentos import ruc_valido
    from core.models import Ajustes

    if not Ajustes.cargar().ruc:
        raise ComprobanteError("Falta el RUC del negocio (Datos del negocio) para emitir comprobantes.")
    if sol["tipo"] == "F":
        if not (sol["doc"].isdigit() and len(sol["doc"]) == 11 and ruc_valido(sol["doc"])):
            raise ComprobanteError("Para la factura escribe un RUC válido (11 dígitos).")
        if not sol["nombre"]:
            raise ComprobanteError("Para la factura escribe la razón social.")
        if not sol["direccion"]:
            raise ComprobanteError("Para la factura escribe la dirección fiscal del cliente.")
        if credito:
            if not Config.cargar().credito_activo:
                raise ComprobanteError("La factura al crédito no está activada (Configuración → Facturación). Emite boleta o cobra al contado.")
            if sol.get("vence") == "mal" or (sol.get("vence") and sol["vence"] <= timezone.localdate()):
                raise ComprobanteError("La fecha de pago de la factura al crédito tiene que ser posterior a hoy.")
    elif sol["doc"] and tipo_documento(sol["doc"]) == "1" and len(sol["doc"]) != 8:
        raise ComprobanteError("El DNI tiene 8 dígitos.")


# --- Armado ------------------------------------------------------------------------------

def lineas(venta, config):
    """Las líneas con su IGV. El descuento de la venta se reparte entre las líneas; las cortesías (S/ 0) no van."""
    items = [i for i in venta.items.select_related("variante__producto").order_by("id") if i.subtotal > 0]
    if not items:
        raise ComprobanteError("La venta no tiene nada que facturar (todo fue cortesía).")
    total = _r(venta.total)
    suma = sum((i.subtotal for i in items), Decimal("0"))
    tasa = config.igv / Decimal("100") if config.afectacion == Config.Afectacion.GRAVADO else Decimal("0")
    out, acumulado = [], Decimal("0")
    for n, i in enumerate(items):
        t = total - acumulado if n == len(items) - 1 else _r(i.subtotal * total / suma)
        acumulado += t
        cantidad = i.cantidad.normalize()
        precio = (t / i.cantidad).quantize(Decimal("0.0000000001"))
        sub = _r(t / (1 + tasa))
        unidad = "ZZ" if i.variante.producto.es_servicio else UNIDADES.get(i.variante.producto.unidad, "NIU")
        out.append({"descripcion": i.descripcion[:250], "codigo": i.variante.codigo or "", "unidad": unidad,
                    "cantidad": f"{cantidad:f}", "precio_unitario": f"{precio:f}",
                    "valor_unitario": f"{(precio / (1 + tasa)).quantize(Decimal('0.0000000001')):f}",
                    "subtotal": f"{sub:.2f}", "igv": f"{t - sub:.2f}", "total": f"{t:.2f}", "afectacion": config.afectacion})
    return out


def serie_para(venta, campo, config):
    """La serie de la caja donde se cobró la venta (Caja 1 → B001, Barra → B002) o la general."""
    sesion = getattr(venta, "sesion_caja", None)
    punto = sesion.punto if sesion and sesion.punto_id else None
    return punto.serie(campo, config) if punto else getattr(config, campo)


def _numerar(codigo):
    Serie.objects.get_or_create(codigo=codigo)
    s = Serie.objects.select_for_update().get(codigo=codigo)
    s.ultimo += 1
    s.save(update_fields=["ultimo"])
    return s.ultimo


def _totales(detalle, afectacion):
    base = sum((Decimal(i["subtotal"]) for i in detalle), Decimal("0"))
    igv = sum((Decimal(i["igv"]) for i in detalle), Decimal("0"))
    total = sum((Decimal(i["total"]) for i in detalle), Decimal("0"))
    return {"gravada": base if afectacion == "G" else Decimal("0"), "exonerada": base if afectacion == "E" else Decimal("0"),
            "inafecta": base if afectacion == "I" else Decimal("0"), "igv": igv, "total": total}


def crear(venta, sol, usuario):
    """Numera y arma el comprobante de una venta recién registrada (dentro de su transacción)."""
    if not sol:
        return None
    ya = venta.comprobantes.exclude(tipo=Comprobante.Tipo.NOTA_CREDITO).exclude(estado=Comprobante.Estado.RECHAZADO).first()
    if ya:  # la misma venta enviada dos veces (se reintentó con el mismo token)
        return ya
    config = Config.cargar()
    if not config.lista:
        raise ComprobanteError("La facturación no está configurada (falta la ruta o el token del proveedor).")
    total = _r(venta.total)
    tipo_doc = tipo_documento(sol["doc"])
    if sol["tipo"] == "B" and total > LIMITE_BOLETA_SIN_DNI and tipo_doc == "-":
        raise ComprobanteError(f"Para una boleta de más de S/ {LIMITE_BOLETA_SIN_DNI:.0f} se necesita el DNI del cliente.")
    if sol["tipo"] == "B" and tipo_doc != "-" and not sol["nombre"]:
        raise ComprobanteError("Escribe el nombre del cliente junto con su documento.")
    detalle = lineas(venta, config)
    serie = serie_para(venta, "serie_factura" if sol["tipo"] == "F" else "serie_boleta", config)
    credito = {}
    fiado = _r(sum((p.monto for p in venta.pagos.filter(metodo="CRE")), Decimal("0")))
    if sol["tipo"] == "F" and fiado > 0:
        vence = sol.get("vence") if isinstance(sol.get("vence"), date_cls) else timezone.localdate() + timedelta(days=config.credito_dias)
        credito = {"forma_pago": "CRE", "pendiente": fiado, "cuotas": plan_cuotas(fiado, vence, sol.get("cuotas") or 1)}
    return Comprobante.objects.create(**credito,
        venta=venta, tipo=Comprobante.Tipo.FACTURA if sol["tipo"] == "F" else Comprobante.Tipo.BOLETA, serie=serie,
        numero=_numerar(serie), fecha=timezone.localdate(venta.fecha), cliente_tipo_doc=tipo_doc, cliente_doc=sol["doc"],
        cliente_nombre=sol["nombre"], cliente_direccion=sol["direccion"], igv_pct=config.igv, detalle=detalle,
        proveedor=config.proveedor, usuario=usuario, **_totales(detalle, config.afectacion))


def nota_credito_parcial(original, lineas_devueltas, motivo, usuario):
    """Nota de crédito por lo devuelto de una venta (motivo SUNAT 07: devolución por ítem).
    `lineas_devueltas` = [(VentaItem, cantidad, importe)]; el importe ya trae su parte del descuento."""
    config = Config.cargar()
    serie = serie_para(original.venta, "serie_nc_factura" if original.tipo == Comprobante.Tipo.FACTURA else "serie_nc_boleta", config)
    tasa = original.igv_pct / Decimal("100") if config.afectacion == Config.Afectacion.GRAVADO else Decimal("0")
    detalle = []
    for i, cantidad, importe in lineas_devueltas:
        if importe <= 0:
            continue
        t = _r(importe)
        precio = (t / cantidad).quantize(Decimal("0.0000000001"))
        sub = _r(t / (1 + tasa))
        unidad = "ZZ" if i.variante.producto.es_servicio else UNIDADES.get(i.variante.producto.unidad, "NIU")
        detalle.append({"descripcion": i.descripcion[:250], "codigo": i.variante.codigo or "", "unidad": unidad,
                        "cantidad": f"{cantidad.normalize():f}", "precio_unitario": f"{precio:f}",
                        "valor_unitario": f"{(precio / (1 + tasa)).quantize(Decimal('0.0000000001')):f}",
                        "subtotal": f"{sub:.2f}", "igv": f"{t - sub:.2f}", "total": f"{t:.2f}", "afectacion": config.afectacion})
    if not detalle:
        return None
    campos = {k: getattr(original, k) for k in ("cliente_tipo_doc", "cliente_doc", "cliente_nombre", "cliente_direccion", "igv_pct")}
    return Comprobante.objects.create(venta=original.venta, tipo=Comprobante.Tipo.NOTA_CREDITO, serie=serie, numero=_numerar(serie),
                                      fecha=timezone.localdate(), modifica=original, motivo=(motivo or "Devolución por ítem")[:200],
                                      tipo_nota=7, detalle=detalle, proveedor=config.proveedor, usuario=usuario,
                                      **campos, **_totales(detalle, config.afectacion))


def plan_cuotas(monto, primera, n=1, cada_dias=30):
    """Reparte lo que se fió en n cuotas iguales (la última cuadra los céntimos), una cada `cada_dias` desde `primera`."""
    base = (monto / n).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    return [{"n": i + 1, "fecha": (primera + timedelta(days=cada_dias * i)).isoformat(),
             "monto": f"{(monto - base * (n - 1)) if i == n - 1 else base:.2f}"} for i in range(n)]


def nota_credito(original, motivo, usuario):
    """Anula un comprobante con una nota de crédito por el total (motivo SUNAT 01: anulación de la operación)."""
    config = Config.cargar()
    serie = serie_para(original.venta, "serie_nc_factura" if original.tipo == Comprobante.Tipo.FACTURA else "serie_nc_boleta", config)
    campos = {k: getattr(original, k) for k in ("cliente_tipo_doc", "cliente_doc", "cliente_nombre", "cliente_direccion", "igv_pct",
                                                "gravada", "exonerada", "inafecta", "igv", "total", "detalle")}
    return Comprobante.objects.create(venta=original.venta, tipo=Comprobante.Tipo.NOTA_CREDITO, serie=serie, numero=_numerar(serie),
                                      fecha=timezone.localdate(), modifica=original, motivo=(motivo or "Anulación de la operación")[:200],
                                      proveedor=config.proveedor, usuario=usuario, **campos)


# --- Envío -------------------------------------------------------------------------------

def enviar(c):
    """Envía (o consulta, si ya se envió) y guarda la respuesta. Lanza ErrorConexion si no hay respuesta."""
    from core.models import Ajustes

    if c.estado == Comprobante.Estado.ACEPTADO:
        return c
    if c.es_nota and c.modifica.estado in (Comprobante.Estado.PENDIENTE,):
        enviar(c.modifica)  # primero el comprobante que se anula
    con = conector(Config.cargar() if Config.cargar().proveedor == c.proveedor else _config_de(c), Ajustes.cargar().ruc)
    c.intentos += 1
    try:
        res = con.consultar(c) if c.estado == Comprobante.Estado.ENVIADO else con.emitir(c)
    except ErrorConexion as e:
        c.mensaje = str(e)[:500]
        c.save(update_fields=["intentos", "mensaje"])
        raise
    c.estado, c.mensaje = res.estado, res.mensaje[:500]
    c.enlace_pdf, c.enlace_xml = res.enlace_pdf or c.enlace_pdf, res.enlace_xml or c.enlace_xml
    c.hash, c.qr = res.hash or c.hash, res.qr or c.qr
    c.enviado_en = c.enviado_en or timezone.now()
    c.save()
    return c


def _config_de(c):
    """Si se cambió de proveedor, lo ya emitido se sigue consultando con el que lo emitió (misma ruta y token)."""
    config = Config.cargar()
    config.proveedor = c.proveedor
    return config


def enviar_seguro(c):
    """Para usar justo después de vender: nunca rompe la venta. Devuelve el comprobante (o None)."""
    if c is None:
        return None
    try:
        enviar(c)
    except ErrorConexion:
        pass
    except Exception:  # noqa: BLE001  (cualquier sorpresa del proveedor: queda pendiente para reintentar)
        log.exception("Error al enviar %s", c)
        Comprobante.objects.filter(pk=c.pk).update(mensaje="Error inesperado al enviar; se reintentará.")
    c.refresh_from_db()
    if c.estado != Comprobante.Estado.PENDIENTE:  # el proveedor respondió: hay conexión, se aprovecha para los atrasados
        try:
            reenviar_pendientes(limite=3, excluir=c.pk)
        except Exception:  # noqa: BLE001
            log.exception("Error al reenviar pendientes")
    return c


def vence_envio(c):
    """Último día en que SUNAT acepta el comprobante."""
    return c.fecha + timedelta(days=PLAZO_SUNAT_DIAS)


def atrasados(minutos=60):
    """Comprobantes que siguen sin respuesta de SUNAT pasado un rato desde que se emitieron (los más urgentes primero)."""
    return (Comprobante.objects.filter(estado__in=POR_ENVIAR, creado__lt=timezone.now() - timedelta(minutes=minutos))
            .order_by("fecha", "id"))


def reenviar_pendientes(limite=30, excluir=None):
    """Pendientes y enviados sin respuesta: se intentan de nuevo (los más antiguos primero). Devuelve (ok, fallidos).
    Corre solo con `python manage.py reenviar_comprobantes` (tarea programada) y después de cada envío que sí tuvo respuesta."""
    ok = mal = 0
    for c in Comprobante.objects.filter(estado__in=POR_ENVIAR).exclude(pk=excluir).order_by("id")[:limite]:
        try:
            enviar(c)
            ok += 1
        except Exception:  # noqa: BLE001
            mal += 1
    return ok, mal


def anular_por_venta(venta, usuario, motivo):
    """Al anular una venta: nota de crédito para cada comprobante suyo que siga vigente."""
    notas = []
    for c in venta.comprobantes.filter(tipo__in=[Comprobante.Tipo.BOLETA, Comprobante.Tipo.FACTURA]).exclude(estado=Comprobante.Estado.RECHAZADO):
        if not c.anulado:
            notas.append(nota_credito(c, motivo, usuario))
    return notas
