"""Qué usa cada tipo de negocio (rubro): módulos, funciones avanzadas y cómo se toman los pedidos.

El rubro solo decide **cómo empieza** el sistema. Después se puede encender o apagar cualquier cosa, y cambiar el rubro
nunca apaga algo que el negocio ya está usando (ver `aplicar`).
"""
from .models import Rubro

# Funciones avanzadas: se ocultan si el negocio no las usa (código, nombre, explicación)
FUNCIONES = [
    ("variantes", "Variantes", "Tallas, colores o tamaños (S/M/L, personal/mediana/familiar, 500 ml/1 L) con su propio precio, código y stock."),
    ("combos", "Combos y packs", "Un producto que agrupa a otros (menú + bebida, pack escolar) y descuenta el stock de cada uno."),
    ("servicios", "Servicios", "Lo que se cobra sin stock (corte, clase, reparación, instalación), con su duración."),
    ("menu", "Menú del día", "Menús a precio fijo (económico, ejecutivo, dietético) donde el cliente elige entrada, segundo y, si "
             "se incluye, bebida o postre. Se arman cada mañana. Necesita el nivel de pedido «Con opciones»."),
    ("agotados", "Agotados del día", "Marcar platos u opciones como agotados solo por hoy, sin tocar el stock."),
    ("atendio", "Quién atendió la venta", "En Vender se elige qué persona del personal atendió al cliente (vendedores a comisión, "
                "servicios cobrados directo). Sale en el reporte de Personal."),
    ("comisiones", "Comisiones del personal", "A cada persona se le pone un % de lo que atiende y el reporte de Personal dice cuánto le toca."),
    ("precios", "Listas de precios", "Precios por cantidad («desde 6 unidades, S/ 2.30») y precios por tipo de cliente "
                "(mayorista, revendedor). Se calculan solos al vender."),
    ("promociones", "Promociones", "2×1, 3×2, % de descuento o precio especial en productos o categorías, con fechas, días y "
                    "horario (happy hour). Se aplican solas al vender."),
    ("monedero", "Monedero", "Un % de cada compra pagada vuelve al cliente registrado como saldo a favor para su próxima compra "
                 "(por ejemplo 2 %, vence a los 90 días)."),
    ("pagos", "Pagos al personal", "Sueldo fijo de cada persona (por semana, quincena o mes), pagos y adelantos ligados a la persona "
              "y cuánto falta pagarle a cada uno."),
]
CODIGOS_FUNCIONES = [f[0] for f in FUNCIONES]

# encendido: módulos que vienen activos; opcional: se ofrecen; funciones: las avanzadas que vienen activas
PERFILES = {
    Rubro.TIENDA: {"encendido": {"mostrador", "caja", "clientes", "reportes", "compras"}, "opcional": {"facturacion", "delivery"},
                   "funciones": {"variantes"}, "nivel_pedido": 1},
    Rubro.ROPA: {"encendido": {"mostrador", "caja", "clientes", "reportes", "compras"}, "opcional": {"facturacion", "delivery"},
                 "funciones": {"variantes"}, "nivel_pedido": 1},
    Rubro.LIBRERIA: {"encendido": {"mostrador", "caja", "clientes", "reportes", "compras"}, "opcional": {"facturacion", "delivery"},
                     "funciones": {"variantes", "combos"}, "nivel_pedido": 1},
    Rubro.RESTAURANTE: {"encendido": {"mesas", "caja", "reportes"},
                        "opcional": {"mostrador", "cocina", "delivery", "clientes", "facturacion", "reservas", "compras"},
                        "funciones": {"variantes", "combos", "agotados", "menu"}, "nivel_pedido": 2},
    Rubro.PELUQUERIA: {"encendido": {"mostrador", "caja", "clientes", "reportes"}, "opcional": {"facturacion", "cobranzas", "citas", "compras"},
                       "funciones": {"servicios", "variantes"}, "nivel_pedido": 1},
    Rubro.ACADEMIA: {"encendido": {"cobranzas", "clientes", "caja", "reportes"}, "opcional": {"mostrador", "facturacion", "compras"},
                     "funciones": {"servicios"}, "nivel_pedido": 1},
    Rubro.OTRO: {"encendido": {"mostrador", "caja", "reportes"},
                 "opcional": {"clientes", "facturacion", "delivery", "mesas", "cocina", "cobranzas", "reservas", "citas", "compras"},
                 "funciones": {"variantes", "combos", "servicios"}, "nivel_pedido": 1},
}


def perfil(rubro):
    return PERFILES.get(rubro, PERFILES[Rubro.OTRO])


def en_uso(funcion):
    """¿El negocio ya tiene datos de esta función? Entonces no se apaga sola."""
    from django.db.models import Count

    from productos.models import Producto

    if funcion == "variantes":
        return Producto.objects.annotate(n=Count("variantes")).filter(n__gt=1).exists()
    if funcion == "combos":
        return Producto.objects.filter(tipo=Producto.Tipo.COMBO).exists()
    if funcion == "servicios":
        return Producto.objects.filter(tipo=Producto.Tipo.SERVICIO, activo=True).exists()
    if funcion == "comisiones":
        from personal.models import Persona

        return Persona.objects.filter(comision__gt=0).exists()
    if funcion == "atendio":
        from ventas.models import Venta

        return Venta.objects.filter(atendio_persona__isnull=False).exists()
    if funcion == "pagos":
        from caja.models import MovimientoCaja
        from personal.models import Persona

        return Persona.objects.filter(sueldo__gt=0).exists() or MovimientoCaja.objects.filter(persona__isnull=False).exists()
    if funcion == "precios":
        from productos.models import ListaPrecios, PrecioEspecial

        return PrecioEspecial.objects.exists() or ListaPrecios.objects.filter(clientes__isnull=False).exists()
    if funcion == "promociones":
        from productos.models import Promocion

        return Promocion.objects.filter(activa=True).exists()
    if funcion == "monedero":
        from clientes.models import MovimientoSaldo

        return MovimientoSaldo.objects.filter(tipo="MON").exists()
    if funcion == "menu":
        from productos.models import GrupoOpciones

        return GrupoOpciones.objects.filter(diario=True, productos__activo=True).exists()
    if funcion == "agotados":
        return False  # se reinicia cada día: apagarla no pierde nada
    return False


def modulo_en_uso(codigo):
    """¿El módulo tiene datos? (para no apagarlo al aplicar lo recomendado)."""
    if codigo == "mesas":
        from mesas.models import Mesa

        return Mesa.objects.exists()
    if codigo == "delivery":
        from mesas.models import Cuenta

        return Cuenta.objects.filter(tipo=Cuenta.Tipo.DELIVERY).exists()
    if codigo == "clientes":
        from clientes.models import Cliente

        return Cliente.objects.exists()
    if codigo == "cobranzas":
        from cobranzas.models import Inscripcion

        return Inscripcion.objects.exists()
    if codigo == "citas":
        from citas.models import Cita

        return Cita.objects.exists()
    if codigo == "reservas":
        from reservas.models import Reserva

        return Reserva.objects.exists()
    if codigo == "facturacion":
        from facturacion.models import Comprobante

        return Comprobante.objects.exists()
    if codigo == "compras":
        from compras.models import Compra

        return Compra.objects.exists()
    return False


def aplicar(ajustes, rubro=None, modulos=False, forzar=False):
    """Ajusta el sistema al rubro. Enciende lo que el rubro usa y apaga lo demás **solo si no está en uso**.

    - modulos=True también toca los módulos (lo hace el administrador principal, o la demo).
    - forzar=True deja todo exactamente como el perfil (solo para datos de ejemplo nuevos).
    Devuelve (encendidos, apagados) con los nombres, para avisar al usuario."""
    from .permisos import MODULOS, NOMBRE_MODULO

    rubro = rubro or ajustes.rubro
    p = perfil(rubro)
    nombres = dict((f[0], f[1]) for f in FUNCIONES)
    encendidos, apagados = [], []
    inactivas = set(ajustes.funciones_inactivas or [])
    for f in CODIGOS_FUNCIONES:
        if f in p["funciones"] and f in inactivas:
            inactivas.discard(f)
            encendidos.append(nombres[f])
        elif f not in p["funciones"] and f not in inactivas and (forzar or not en_uso(f)):
            inactivas.add(f)
            apagados.append(nombres[f])
    ajustes.funciones_inactivas = [f for f in CODIGOS_FUNCIONES if f in inactivas]
    campos = ["funciones_inactivas"]
    if forzar or (p["nivel_pedido"] > ajustes.nivel_pedido):
        ajustes.nivel_pedido = p["nivel_pedido"]
        campos.append("nivel_pedido")
    elif p["nivel_pedido"] < ajustes.nivel_pedido:
        from productos.models import Producto

        if not Producto.objects.filter(grupos__isnull=False).exists():
            ajustes.nivel_pedido = p["nivel_pedido"]
            campos.append("nivel_pedido")
    if modulos:
        inactivos = set(ajustes.modulos_inactivos or [])
        for codigo, *_ in MODULOS:
            if codigo in p["encendido"] and codigo in inactivos:
                inactivos.discard(codigo)
                encendidos.append(NOMBRE_MODULO[codigo])
            elif codigo not in p["encendido"] | p["opcional"] and codigo not in inactivos and (forzar or not modulo_en_uso(codigo)):
                inactivos.add(codigo)
                apagados.append(NOMBRE_MODULO[codigo])
            elif forzar and codigo in p["opcional"] and codigo not in inactivos:
                inactivos.add(codigo)
        ajustes.modulos_inactivos = [m[0] for m in MODULOS if m[0] in inactivos]
        campos.append("modulos_inactivos")
    ajustes.save(update_fields=campos)
    return encendidos, apagados
