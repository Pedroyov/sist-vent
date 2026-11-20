import re
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


def inicio_dia(dia):
    """Medianoche (hora local) del día: el límite que sí usa el índice de una fecha con hora."""
    from django.utils import timezone

    return timezone.make_aware(datetime.combine(dia, time.min))


def dias(campo, desde, hasta=None, *, antes_de=None):
    """Filtro de los días locales [desde, hasta] (o [desde, antes_de)) sobre un campo fecha-hora:
    `Venta.objects.filter(**dias("fecha", desde, hasta))`. A diferencia de `fecha__date`, que convierte cada fila a fecha
    local y obliga a recorrer toda la tabla en PostgreSQL, compara contra dos instantes y aprovecha el índice."""
    fin = antes_de if antes_de is not None else (hasta or desde) + timedelta(days=1)
    return {f"{campo}__gte": inicio_dia(desde), f"{campo}__lt": inicio_dia(fin)}


def entero(valor):
    """Convierte a entero un id que llega por GET/POST; None si no es un número (evita errores 500)."""
    texto = str(valor if valor is not None else "").strip()
    return int(texto) if texto.isdigit() else None


def url_segura(request, url, defecto="/"):
    """Solo deja volver a direcciones de este mismo sistema (evita mandar al usuario a otro sitio)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return defecto


def numero_whatsapp(telefono):
    """'987 654 321' -> '51987654321' (para enlaces wa.me). Vacío si no hay número."""
    d = re.sub(r"\D", "", telefono or "")
    if len(d) == 9 and d.startswith("9"):
        d = "51" + d
    return d


def enlace_whatsapp(telefono=None, texto=""):
    """El único lugar donde se arma un enlace de WhatsApp (wa.me), con el mensaje listo si se da `texto`.

    - Con teléfono: abre el chat con esa persona. Si el número no sirve, devuelve "" (para no mostrar el botón).
    - Sin teléfono (None): abre WhatsApp para elegir a quién mandarlo (compartir un ticket, mis horarios…)."""
    from urllib.parse import quote

    if telefono is None:
        base = "https://wa.me/"
    else:
        numero = numero_whatsapp(telefono)
        if not numero:
            return ""
        base = f"https://wa.me/{numero}"
    return f"{base}?text={quote(texto)}" if texto else base


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
