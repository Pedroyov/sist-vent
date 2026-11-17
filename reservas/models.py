"""Reservas de mesa (restaurantes).

Una reserva es un nombre, un celular, día, hora y cuántas personas; la mesa es opcional. En el mapa de mesas, la mesa
reservada se ve como «Reservada» un rato antes (Config.antes) y, cuando llegan, la reserva abre la cuenta de la mesa.
Si pasa la tolerancia y no llegaron, la mesa vuelve a verse libre y la reserva queda como atrasada (luego «No vino»).
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Config(models.Model):
    """Opciones de reservas (una sola fila)."""

    antes = models.PositiveSmallIntegerField(
        "marcar la mesa como reservada", default=60, validators=[MinValueValidator(10), MaxValueValidator(240)],
        help_text="Minutos antes de la hora en que la mesa se ve «Reservada» en el mapa.")
    tolerancia = models.PositiveSmallIntegerField(
        "tolerancia", default=20, validators=[MinValueValidator(5), MaxValueValidator(120)],
        help_text="Minutos que se guarda la mesa después de la hora. Luego vuelve a verse libre.")
    duracion = models.PositiveSmallIntegerField(
        "cuánto dura una reserva", default=120, validators=[MinValueValidator(30), MaxValueValidator(360)],
        help_text="Minutos que ocupa la mesa. Sirve para avisar si dos reservas de la misma mesa se cruzan.")

    class Meta:
        verbose_name = "configuración de reservas"
        verbose_name_plural = "configuración de reservas"

    def __str__(self):
        return "Configuración de reservas"

    @classmethod
    def cargar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Reserva(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Por confirmar"
        CONFIRMADA = "CON", "Confirmada"
        LLEGO = "LLE", "Llegó"
        NO_VINO = "NOV", "No vino"
        CANCELADA = "CAN", "Cancelada"

    ACTIVAS = (Estado.PENDIENTE, Estado.CONFIRMADA)

    fecha = models.DateField()
    hora = models.TimeField()
    personas = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(200)])
    nombre = models.CharField(max_length=60)
    telefono = models.CharField("celular", max_length=20, blank=True)
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservas")
    mesa = models.ForeignKey("mesas.Mesa", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservas")
    nota = models.CharField(max_length=200, blank=True, help_text="Ej.: cumpleaños, silla para bebé, cerca de la ventana.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    cuenta = models.ForeignKey("mesas.Cuenta", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservas",
                               help_text="La cuenta que se abrió cuando llegaron.")
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservas_creadas")
    creada_en = models.DateTimeField(default=timezone.now)
    cambiada_en = models.DateTimeField(null=True, blank=True)
    cambiada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["fecha", "hora", "pk"]
        indexes = [models.Index(fields=["fecha", "estado"])]

    def __str__(self):
        return f"{self.nombre} · {self.fecha:%d/%m} {self.hora:%H:%M} ({self.personas})"

    @property
    def momento(self):
        return timezone.make_aware(datetime.combine(self.fecha, self.hora))

    @property
    def activa(self):
        return self.estado in self.ACTIVAS

    def atrasada(self, ahora=None, cfg=None):
        """Sigue activa y ya pasó la tolerancia (no llegaron)."""
        cfg = cfg or Config.cargar()
        return self.activa and (ahora or timezone.now()) > self.momento + timedelta(minutes=cfg.tolerancia)

    @property
    def whatsapp(self):
        from core.utils import numero_whatsapp

        return numero_whatsapp(self.telefono)
