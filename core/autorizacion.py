"""Autorización de un supervisor en el momento (descuentos, cortesías…).

Si quien opera tiene el permiso, autoriza él mismo. Si no, un supervisor escribe su usuario y clave en el mismo
cuadro: queda registrado quién autorizó. Los intentos fallidos se bloquean igual que en el ingreso.
"""
from hashlib import sha256

from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache

from .permisos import puede

MAX_INTENTOS, ESPERA = 5, 15 * 60


class AutorizacionError(Exception):
    pass


def autorizar(request, permiso, usuario="", clave=""):
    """Devuelve el usuario que autoriza o lanza AutorizacionError."""
    if puede(request.user, permiso):
        return request.user
    usuario = (usuario or "").strip()
    if not usuario or not clave:
        raise AutorizacionError("Necesita autorización: un supervisor debe escribir su usuario y clave.")
    clave_cache = "autoriza:" + sha256(f"{request.user.pk}:{usuario.lower()}".encode()).hexdigest()[:32]
    if cache.get(clave_cache, 0) >= MAX_INTENTOS:
        raise AutorizacionError("Demasiados intentos fallidos. Espera 15 minutos.")
    # el usuario se escribe en el celular: no importan mayúsculas ni minúsculas
    real = get_user_model().objects.filter(username__iexact=usuario).values_list("username", flat=True).first() or usuario
    supervisor = authenticate(request, username=real, password=clave)
    if supervisor is None or not supervisor.is_active or not puede(supervisor, permiso):
        try:
            cache.incr(clave_cache)
        except ValueError:
            cache.set(clave_cache, 1, ESPERA)
        raise AutorizacionError("Usuario o clave incorrectos, o ese usuario no puede autorizar esto.")
    cache.delete(clave_cache)
    return supervisor
