"""Datos secretos guardados cifrados en la base de datos (token de Nubefact, secreto del código del celular).

Si alguien obtiene una copia de la base (un respaldo perdido, un acceso indebido), no puede usar esos secretos sin la clave
del servidor. La clave es CLAVE_CIFRADO del .env (o, si no está, la SECRET_KEY). Si se cambia, lo cifrado ya no se puede
leer: hay que volver a escribir el token y volver a activar el código del celular. Por eso en producción conviene poner
CLAVE_CIFRADO aparte y guardarla en un lugar seguro.
"""
import base64
import hashlib
import logging

from django.conf import settings
from django.db import models

PREFIJO = "enc1:"
log = logging.getLogger(__name__)


def _fernet():
    from cryptography.fernet import Fernet

    clave = getattr(settings, "CLAVE_CIFRADO", "") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"sist-vent:{clave}".encode()).digest()))


def cifrar(texto):
    if not texto or str(texto).startswith(PREFIJO):
        return texto
    return PREFIJO + _fernet().encrypt(str(texto).encode()).decode()


def descifrar(valor):
    """Lo guardado antes de cifrar (texto plano) se devuelve tal cual. Si la clave cambió, devuelve "" y lo anota."""
    if not valor or not str(valor).startswith(PREFIJO):
        return valor
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(str(valor)[len(PREFIJO):].encode()).decode()
    except InvalidToken:
        log.error("No se pudo descifrar un dato: ¿cambió CLAVE_CIFRADO o SECRET_KEY?")
        return ""


class CampoCifrado(models.TextField):
    """Se lee y se escribe como texto normal; en la base queda cifrado."""

    def from_db_value(self, value, expression, connection):
        return descifrar(value)

    def to_python(self, value):
        return descifrar(value)

    def get_prep_value(self, value):
        return cifrar(super().get_prep_value(value))
