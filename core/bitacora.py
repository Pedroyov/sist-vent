"""Bitácora: el único lugar donde se anotan las acciones críticas.

    from core.bitacora import anotar
    anotar("venta.anulada", f"Venta {v.numero_str} anulada: {motivo}", objeto=v, despues={"total": v.total})

Se llama dentro de la transacción de la acción: si la acción se deshace, la fila también. Usuario e IP salen de la
petición en curso (lo deja `BitacoraMiddleware`), o se pasan a mano (tareas sin petición, pruebas).
"""
from contextvars import ContextVar
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

_peticion = ContextVar("bitacora_peticion", default=None)

# código → (texto para la pantalla, grupo para filtrar)
ACCIONES = {
    "venta.anulada": ("Venta anulada", "Anulaciones"),
    "venta.devolucion": ("Devolución de productos", "Anulaciones"),
    "compra.anulada": ("Compra anulada", "Anulaciones"),
    "fiado.pago_anulado": ("Pago de fiado anulado", "Anulaciones"),
    "cuota.pago_anulado": ("Pago de cuotas anulado", "Anulaciones"),
    "gasto.anulado": ("Gasto anulado", "Anulaciones"),
    "producto.precio": ("Cambio de precio", "Precios y costos"),
    "producto.costo": ("Cambio de costo", "Precios y costos"),
    "producto.eliminado": ("Producto eliminado", "Precios y costos"),
    "productos.importados": ("Productos importados de Excel", "Precios y costos"),
    "venta.descuento": ("Descuento", "Descuentos y cortesías"),
    "venta.precio": ("Precio cambiado al vender", "Descuentos y cortesías"),
    "mesa.cortesia": ("Cortesía", "Descuentos y cortesías"),
    "caja.diferencia": ("Cierre con diferencia", "Caja"),
    "caja.cierre_ajeno": ("Caja cerrada por otra persona", "Caja"),
    "caja.apertura": ("Apertura con monto distinto", "Caja"),
    "caja.correccion": ("Conteo de caja corregido", "Caja"),
    "caja.reabierta": ("Caja reabierta", "Caja"),
    "caja.salida_olvidada": ("Salida agregada a una caja cerrada", "Caja"),
    "conciliacion.diferencia": ("Conciliación con diferencia", "Caja"),
    "conciliacion.cambiada": ("Conciliación corregida", "Caja"),
    "pago.no_llego": ("Cobro electrónico que no llegó", "Caja"),
    "pago.no_llego_quitado": ("Se quitó «no llegó» a un cobro", "Caja"),
    "stock.ajuste": ("Ajuste de stock por conteo", "Stock"),
    "stock.salida": ("Salida de stock (merma, uso interno)", "Stock"),
    "cliente.saldo_devuelto": ("Saldo a favor devuelto en efectivo", "Clientes"),
    "cliente.limite": ("Cambio de límite de fiado", "Clientes"),
    "fiado.sobre_limite": ("Fiado sobre el límite", "Clientes"),
    "fiado.con_vencido": ("Fiado con deuda vencida", "Clientes"),
    "cliente.plazo": ("Cambio de plazo del fiado", "Clientes"),
    "cliente.lista": ("Cambio de lista de precios", "Clientes"),
    "promocion.cambio": ("Promoción creada o cambiada", "Precios y costos"),
    "fiado.incobrable": ("Deuda marcada incobrable", "Clientes"),
    "usuario.creado": ("Usuario creado", "Usuarios y permisos"),
    "usuario.modificado": ("Usuario modificado", "Usuarios y permisos"),
    "rol.permisos": ("Permisos de roles cambiados", "Usuarios y permisos"),
    "rol.guardado": ("Rol creado o renombrado", "Usuarios y permisos"),
    "config.modulos": ("Módulos encendidos o apagados", "Configuración"),
    "config.negocio": ("Datos del negocio", "Configuración"),
    "config.facturacion": ("Configuración de facturación", "Configuración"),
    "ingreso": ("Ingreso de Administración", "Ingreso"),
    "ingreso.bloqueado": ("Ingreso bloqueado por intentos", "Ingreso"),
    "ingreso.respaldo": ("Ingreso con código de respaldo", "Ingreso"),
    "ingreso.2fa_activado": ("Código del celular activado", "Ingreso"),
    "ingreso.2fa_desactivado": ("Código del celular quitado por su dueño", "Ingreso"),
    "ingreso.2fa_quitado": ("Código del celular quitado por Administración", "Ingreso"),
}
GRUPOS = list(dict.fromkeys(g for _, g in ACCIONES.values()))


def texto_accion(codigo):
    return ACCIONES.get(codigo, (codigo, ""))[0]


class BitacoraMiddleware:
    """Deja la petición a mano para que `anotar()` sepa quién y desde qué IP, sin pasarlo por todas las funciones."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        marca = _peticion.set(request)
        try:
            return self.get_response(request)
        finally:
            _peticion.reset(marca)


def _limpio(valor):
    """Para guardar en JSON: Decimal y fechas como texto, sin perder nada."""
    if isinstance(valor, dict):
        return {str(k): _limpio(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [_limpio(v) for v in valor]
    if isinstance(valor, Decimal):
        return str(valor)
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)


def anotar(accion, descripcion, objeto=None, antes=None, despues=None, usuario=None, ip=None):
    from core.utils import ip_cliente
    from ventas.models import Correlativo

    from .models import Bitacora

    peticion = _peticion.get()
    if usuario is None and peticion is not None and getattr(peticion.user, "is_authenticated", False):
        usuario = peticion.user
    if ip is None:
        ip = ip_cliente(peticion) if peticion is not None else ""
    with transaction.atomic():
        n = Correlativo.siguiente("bitacora")  # bloquea: las huellas se encadenan en orden, sin carreras
        anterior = Bitacora.objects.filter(n__lt=n).order_by("-n").values_list("huella", flat=True).first() or ""
        b = Bitacora(n=n, fecha=timezone.now(), usuario=usuario if getattr(usuario, "pk", None) else None,
                     usuario_nombre=((usuario.get_full_name() or usuario.username) if getattr(usuario, "pk", None) else "")[:150],
                     ip=(ip or "")[:45], accion=accion[:40], descripcion=" ".join(str(descripcion).split())[:300],
                     objeto_tipo=(objeto._meta.model_name if objeto is not None else "")[:40],
                     objeto_id=str(objeto.pk if objeto is not None else "")[:20],
                     antes=_limpio(antes) if antes is not None else None, despues=_limpio(despues) if despues is not None else None,
                     huella_anterior=anterior)
        b.huella = b.calcular_huella()
        b.save()
    return b


def cambios_form(form, campos=None, ocultos=()):
    """{campo: [antes, después]} de lo que cambió en un formulario (los `ocultos`, como una clave, sin su valor)."""
    salida = {}
    for c in form.changed_data:
        if campos is not None and c not in campos:
            continue
        antes, despues = form.initial.get(c), form.cleaned_data.get(c)
        if hasattr(antes, "pk"):
            antes = str(antes)
        if c in ocultos:
            antes, despues = "•••", "(cambiado)"
        salida[c] = [antes, despues]
    return salida


def verificar():
    """Recorre la bitácora en orden y comprueba la cadena de huellas. Devuelve {"ok", "filas", "rota_en", "motivo"}."""
    from .models import Bitacora

    previa, esperado, filas = "", None, 0
    for b in Bitacora.objects.order_by("n").iterator():
        filas += 1
        if esperado is not None and b.n != esperado:
            return {"ok": False, "filas": filas, "rota_en": esperado, "motivo": f"Faltan las entradas {esperado} a {b.n - 1}: fueron borradas."}
        if b.huella_anterior != previa:
            return {"ok": False, "filas": filas, "rota_en": b.n, "motivo": "No encadena con la entrada anterior: se borró o cambió algo antes."}
        if b.calcular_huella() != b.huella:
            return {"ok": False, "filas": filas, "rota_en": b.n, "motivo": "Su contenido fue cambiado después de anotarse."}
        previa, esperado = b.huella, b.n + 1
    return {"ok": True, "filas": filas, "rota_en": None, "motivo": ""}


def de_objetos(objetos, limite=5):
    """Las últimas entradas sobre unos objetos (un producto y sus variantes, un cliente), para mostrarlas en su ficha."""
    from django.db.models import Q

    from .models import Bitacora

    filtro = Q(pk__in=[])
    for o in objetos:
        filtro |= Q(objeto_tipo=o._meta.model_name, objeto_id=str(o.pk))
    lista = list(Bitacora.objects.filter(filtro).order_by("-n")[:limite])
    for b in lista:
        b.texto = texto_accion(b.accion)
    return lista


def equipo(agente):
    """«Chrome en Android», «Safari en iPhone»: lo justo para reconocer el equipo; el texto completo va en «después»."""
    a = agente or ""
    sistema = next((n for clave, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                         ("Mac OS", "Mac"), ("CrOS", "Chromebook"), ("Linux", "Linux")) if clave in a), "otro equipo")
    navegador = next((n for clave, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
                                           ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if clave in a), "")
    return f"{navegador} en {sistema}" if navegador else sistema
