from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


def entero(valor):
    """Convierte a entero un id que llega por GET/POST; None si no es un número (evita errores 500)."""
    texto = str(valor if valor is not None else "").strip()
    return int(texto) if texto.isdigit() else None



@deconstructible
class TamanoMaximo:
    """Validador: límite de tamaño para archivos subidos (en MB)."""

    def __init__(self, megas=5):
        self.megas = megas

    def __call__(self, archivo):
        if archivo and getattr(archivo, "size", 0) > self.megas * 1024 * 1024:
            raise ValidationError(f"El archivo es muy grande (máximo {self.megas} MB).")

    def __eq__(self, otro):
        return isinstance(otro, TamanoMaximo) and otro.megas == self.megas
