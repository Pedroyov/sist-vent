"""
Módulos y permisos del sistema.

- Cada rol (grupo de Django) tiene una lista de permisos que se marca en
  Configuración → Roles y permisos.
- Administración y el superusuario siempre tienen todos los permisos (así nadie
  puede quedarse sin acceso a la configuración).
- Un módulo desactivado desaparece para todos, aunque el rol tenga el permiso.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

ADMINISTRACION = "Administración"
CAJERO = "Cajero"
VENDEDOR = "Vendedor"
COCINA = "Cocina"
ROLES_BASE = [ADMINISTRACION, CAJERO, VENDEDOR, COCINA]

# Módulos que se pueden desactivar. Configuración es la base y siempre está activa.
# Al crear una app nueva se agrega aquí, por ejemplo:
#   ("ventas", "Ventas", "bi-cart3", "Punto de venta, tickets y anulaciones."),
#   ("productos", "Productos", "bi-box-seam", "Catálogo, precios, variantes (talla/color) y stock."),
#   ("caja", "Caja", "bi-cash-stack", "Apertura, cierre, ingresos y egresos."),
#   ("clientes", "Clientes", "bi-people", "Clientes, historial y deudas."),
MODULOS = [
    ("caja", "Caja", "bi-safe2", "Apertura y cierre de caja por turno, ingresos y egresos, arqueo del efectivo."),
    ("mesas", "Mesas", "bi-grid-3x3-gap", "Para restaurantes: mapa de mesas, pedidos con notas, envío a cocina, precuenta y cobro por mesa."),
    ("clientes", "Clientes y fiado", "bi-people", "Clientes con DNI/RUC, ventas al fiado con límite, pagos de deudas y recordatorios por WhatsApp."),
    ("reportes", "Reportes", "bi-bar-chart", "Ventas por día y hora, lo más vendido, personal, mesas, inventario, deudores y control."),
    ("ventas", "Ventas", "bi-cart3", "Punto de venta, tickets, ventas del día y anulaciones."),
    ("productos", "Productos", "bi-box-seam", "Catálogo de productos y servicios, variantes (talla, color, tamaño), precios y stock."),
]
MODULOS_BASE = ("config",)

# (código, módulo, descripción, roles que lo tienen por defecto)
# Administración y el superusuario siempre tienen todos.
PERMISOS = [
    ("caja.usar", "caja", "Abrir y cerrar su propia caja, registrar ingresos y egresos", [CAJERO, VENDEDOR]),
    ("caja.ver", "caja", "Ver todas las cajas, sus cierres y diferencias; cerrar la caja de otro", []),

    ("mesas.atender", "mesas", "Abrir mesas, tomar pedidos, enviar a cocina, precuenta, cambiar y juntar mesas", [CAJERO, VENDEDOR]),
    ("mesas.cobrar", "mesas", "Cobrar mesas (todo o dividiendo la cuenta)", [CAJERO]),
    ("mesas.cortesia", "mesas", "Dar cortesías (platos sin cobrar) o autorizarlas con su clave", []),
    ("mesas.anular", "mesas", "Quitar productos ya enviados a cocina y anular cuentas", []),
    ("mesas.cocina", "mesas", "Usar la pantalla de cocina: ver pedidos y marcarlos como listos", [COCINA]),
    ("mesas.configurar", "mesas", "Crear y editar zonas y mesas", []),

    ("clientes.ver", "clientes", "Ver clientes, lo que deben y su estado de cuenta", [CAJERO, VENDEDOR]),
    ("clientes.editar", "clientes", "Registrar y editar clientes", [CAJERO, VENDEDOR]),
    ("clientes.fiar", "clientes", "Vender al fiado", [CAJERO]),
    ("clientes.cobrar", "clientes", "Registrar pagos de deudas", [CAJERO]),
    ("clientes.limite", "clientes", "Fiar por encima del límite, cambiar límites y anular pagos de deudas", []),

    ("reportes.ver", "reportes", "Ver los reportes del negocio", []),

    ("ventas.vender", "ventas", "Vender en el punto de venta y ver sus propias ventas", [CAJERO, VENDEDOR]),
    ("ventas.ver", "ventas", "Ver todas las ventas y los totales del día", [CAJERO]),
    ("ventas.precio", "ventas", "Cambiar precios y dar descuentos (o autorizarlos con su clave)", []),
    ("ventas.anular", "ventas", "Anular ventas (devuelve el stock)", []),

    ("productos.ver", "productos", "Ver productos, precios y stock", [CAJERO, VENDEDOR]),
    ("productos.editar", "productos", "Crear y editar productos, variantes, precios y categorías; importar Excel", []),
    ("productos.stock", "productos", "Registrar ingresos, salidas y conteos de stock; ver movimientos", []),
    ("productos.costos", "productos", "Ver costos y ganancia", []),
    ("productos.agotar", "productos", "Marcar productos y opciones como agotados por hoy", [CAJERO, VENDEDOR, COCINA]),
    ("productos.menu", "productos", "Armar el menú del día (entradas y segundos de hoy)", [CAJERO, COCINA]),

    ("config.negocio", "config", "Datos del negocio (nombre, logo, RUC, contacto)", []),
    ("config.usuarios", "config", "Crear y editar usuarios (el rol Administración solo lo da Administración)", []),
]
CODIGOS = [p[0] for p in PERMISOS]
MODULO_DE = {p[0]: p[1] for p in PERMISOS}
NOMBRE_MODULO = {"config": "Configuración", **{m[0]: m[1] for m in MODULOS}}


def permisos_por_defecto(rol):
    if rol == ADMINISTRACION:
        return list(CODIGOS)
    return [p[0] for p in PERMISOS if rol in p[3]]


def modulos_activos():
    from .models import Ajustes

    inactivos = set(Ajustes.cargar().modulos_inactivos)
    return {m[0] for m in MODULOS if m[0] not in inactivos} | set(MODULOS_BASE)


def permisos_de(user):
    """Conjunto de permisos efectivos del usuario (se calcula una vez por petición)."""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    cache = getattr(user, "_sis_permisos", None)
    if cache is not None:
        return cache
    from .models import PermisosRol

    activos = modulos_activos()
    grupos = list(user.groups.values_list("pk", "name"))
    if user.is_superuser or any(nombre == ADMINISTRACION for _, nombre in grupos):
        codigos = set(CODIGOS)
    else:
        codigos = set()
        for lista in PermisosRol.objects.filter(grupo_id__in=[g for g, _ in grupos]).values_list("permisos", flat=True):
            codigos.update(lista or [])
    resultado = frozenset(c for c in codigos if MODULO_DE.get(c) in activos)
    user._sis_permisos = resultado
    user._sis_modulos = activos
    return resultado


def acceso_total(user):
    """Rol Administración o superusuario: tiene todo y es quien maneja roles, permisos y módulos."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name=ADMINISTRACION).exists()


def acceso_total_requerido(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not acceso_total(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return envoltura


def puede(user, *codigos):
    """True si el usuario tiene al menos uno de los permisos."""
    p = permisos_de(user)
    return any(c in p for c in codigos)


def modulo_activo(user, modulo):
    permisos_de(user)
    return modulo in getattr(user, "_sis_modulos", modulos_activos())


def requiere_modulo(modulo):
    """Para vistas sin permiso fijo: solo exige que el módulo esté activo."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if modulo not in modulos_activos():
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador


def permiso_requerido(*codigos):
    """@permiso_requerido("ventas.vender") — basta con tener uno de los permisos indicados."""
    for c in codigos:
        assert c in CODIGOS, f"Permiso desconocido: {c}"

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not puede(request.user, *codigos):
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        envoltura.permisos = codigos
        return envoltura

    return decorador


class PermisosPlantilla(dict):
    """En plantillas: {% if P.config_negocio %} … {% if P.mod_ventas %}"""

    def __init__(self, user):
        super().__init__()
        self.user = user

    def __missing__(self, clave):
        if clave == "acceso_total":
            return acceso_total(self.user)
        if clave.startswith("mod_"):
            return modulo_activo(self.user, clave[4:])
        return puede(self.user, clave.replace("_", ".", 1))

    def __contains__(self, clave):
        return True
