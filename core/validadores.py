"""Validadores de contraseña propios (ver AUTH_PASSWORD_VALIDATORS en config/settings.py)."""
from django.core.exceptions import ValidationError

MINIMO_ADMINISTRACION = 10


class ClaveAdministracion:
    """Las cuentas de Administración (ven el dinero, anulan, cambian permisos) necesitan una clave más larga."""

    def validate(self, password, user=None):
        from .permisos import acceso_total

        if user is not None and getattr(user, "pk", None) and acceso_total(user) and len(password or "") < MINIMO_ADMINISTRACION:
            raise ValidationError(f"Las cuentas de Administración necesitan una contraseña de al menos {MINIMO_ADMINISTRACION} caracteres.",
                                  code="clave_administracion")

    def get_help_text(self):
        return f"Si la cuenta es de Administración, al menos {MINIMO_ADMINISTRACION} caracteres."
