"""Base común de todo lo que se agenda para un día y una hora: reservas de mesa, citas… (y lo que venga: canchas,
salas, clases).

Cada módulo pone **a qué** se reserva (una mesa, una persona) y sus pantallas; aquí está lo que comparten:
- `TurnoBase`: el cliente (nombre, celular y su ficha), la nota, quién lo tomó y quién lo cambió.
- Estados con los mismos códigos: PEN por confirmar, CON confirmada, NOV no vino, CAN cancelada (el «hecho» lo
  define cada uno: Llegó, Atendida…). `cambiar_estado` valida y guarda quién y cuándo.
- `cerrar_pasadas`: lo que quedó activo de días anteriores pasa a «No vino» (sin tareas programadas).
- Textos para los mensajes: hora («8:30 pm»), día («mañana», «el jueves 19/11») y el nombre del negocio.
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

PENDIENTE, CONFIRMADA, NO_VINO, CANCELADA = "PEN", "CON", "NOV", "CAN"


class TurnoBase(models.Model):
    """Campos comunes. Cada modelo agrega: fecha, su hora (`CAMPO_HORA`), estado (con PEN, CON, NOV, CAN y su «hecho»)
    y a qué se reserva."""

    CAMPO_HORA = "hora"
    ACTIVAS = (PENDIENTE, CONFIRMADA)

    nombre = models.CharField(max_length=60)
    telefono = models.CharField("celular", max_length=20, blank=True)
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)ss")
    nota = models.CharField(max_length=200, blank=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="%(class)ss_creadas")
    creada_en = models.DateTimeField(default=timezone.now)
    cambiada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cambiada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def momento(self):
        return timezone.make_aware(datetime.combine(self.fecha, getattr(self, self.CAMPO_HORA)))

    @property
    def activa(self):
        return self.estado in self.ACTIVAS

    @property
    def whatsapp(self):
        from core.utils import numero_whatsapp

        return numero_whatsapp(self.telefono)


def cambiar_estado(obj, usuario, estado, desde, error=ValueError):
    """Pasa a `estado` si está en uno de `desde`; si no, `error` con el estado actual."""
    if obj.estado not in desde:
        raise error(f"La {obj._meta.verbose_name} ya está como «{obj.get_estado_display()}».")
    obj.estado, obj.cambiada_por, obj.cambiada_en = estado, usuario, timezone.now()
    obj.save(update_fields=["estado", "cambiada_por", "cambiada_en"])
    return obj


def cerrar_pasadas(modelo, hoy=None):
    """Lo de días anteriores que nadie marcó queda como «No vino»."""
    hoy = hoy or timezone.localdate()
    return modelo.objects.filter(fecha__lt=hoy, estado__in=modelo.ACTIVAS).update(estado=NO_VINO, cambiada_en=timezone.now())


def por_confirmar(modelo, hoy=None):
    """Cuántos de hoy y mañana faltan confirmar (para el Inicio)."""
    hoy = hoy or timezone.localdate()
    return modelo.objects.filter(fecha__in=(hoy, hoy + timedelta(days=1)), estado=PENDIENTE).count()


# --- Textos para mensajes y pantallas -------------------------------------------------------

def hora_texto(t):
    """20:30 → «8:30 pm». Acepta una hora o minutos desde las 00:00."""
    if isinstance(t, int):
        t = datetime.min.replace(hour=t // 60 % 24, minute=t % 60).time()
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def dia_texto(d, hoy=None):
    """Para una frase: «hoy», «mañana», «el jueves 19/11»."""
    hoy = hoy or timezone.localdate()
    if d == hoy:
        return "hoy"
    if d == hoy + timedelta(days=1):
        return "mañana"
    return f"el {DIAS[d.weekday()]} {d:%d/%m}"


def dia_corto(d, hoy=None):
    """Para una etiqueta: «Hoy 17/11», «Mañana 18/11», «Jueves 19/11»."""
    hoy = hoy or timezone.localdate()
    nombre = "Hoy" if d == hoy else "Mañana" if d == hoy + timedelta(days=1) else DIAS[d.weekday()].capitalize()
    return f"{nombre} {d:%d/%m}"


def negocio():
    from core.models import Ajustes

    return Ajustes.cargar().nombre_mostrar
