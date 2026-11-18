"""
Roles del sistema (grupos de Django).

Lo que puede hacer cada rol se define con permisos (ver core/permisos.py) y se
marca en Configuración → Roles y permisos. Administración y el superusuario siempre
tienen acceso total.
"""
from .permisos import ADMINISTRACION, CAJERO, COCINA, MOZO, PROFESIONAL, ROLES_BASE, VENDEDOR  # noqa: F401

ROLES = ROLES_BASE  # roles que vienen con el sistema


def roles_disponibles():
    """Todos los roles (los del sistema primero y luego los creados por el negocio)."""
    from django.contrib.auth.models import Group

    nombres = list(Group.objects.filter(permisos_sis__isnull=False).values_list("name", flat=True))
    return [r for r in ROLES_BASE if r in nombres] + sorted(n for n in nombres if n not in ROLES_BASE)


def tiene_rol(user, *roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def roles_de(user):
    if user.is_superuser:
        return ["Administrador"]
    return list(user.groups.filter(permisos_sis__isnull=False).values_list("name", flat=True))


# Para la pantalla de ingreso de la demo: qué hace cada rol y el módulo que necesita para tener sentido
_DEMO_ROLES = {
    ADMINISTRACION: ("Administración, ve todo", None),
    CAJERO: ("caja", None),
    VENDEDOR: ("ventas", None),
    MOZO: ("mozo: mesas y pedidos", "mesas"),
    COCINA: ("pantalla de cocina", "cocina"),
    PROFESIONAL: ("su agenda de citas", "citas"),
}


def usuarios_demo(ajustes):
    """Usuarios de prueba que se muestran al ingresar a la demo: solo los que sirven en este negocio."""
    from django.contrib.auth import get_user_model

    lista = []
    for u in get_user_model().objects.filter(is_active=True, is_superuser=False).prefetch_related("groups").order_by("id"):
        rol = next((g.name for g in u.groups.all() if g.name in _DEMO_ROLES), None)
        if rol is None:
            continue
        texto, modulo = _DEMO_ROLES[rol]
        if modulo is None or ajustes.tiene_modulo(modulo):
            lista.append((ROLES_BASE.index(rol), u.username, texto))
    return [(usuario, texto) for _, usuario, texto in sorted(lista)]
