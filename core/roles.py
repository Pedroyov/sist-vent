"""
Roles del sistema (grupos de Django).

Lo que puede hacer cada rol se define con permisos (ver core/permisos.py) y se
marca en Configuración → Roles y permisos. Administración y el superusuario siempre
tienen acceso total.
"""
from .permisos import ADMINISTRACION, CAJERO, ROLES_BASE, VENDEDOR  # noqa: F401

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
