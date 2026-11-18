"""Citas de peluquería, spa, barbería o consultorio.

Quien atiende es una **Persona** del Personal (app `personal`, base del sistema: servicios que hace, usuario
opcional) → su **Horario** semanal (entrada, salida y
refrigerio por día) y sus **Ausencias** (días libres, vacaciones, permisos) → las **Citas** (servicio, cliente, día,
hora de inicio y fin). Los horarios libres se calculan: jornada − refrigerio − ausencias − citas.
"""
from datetime import datetime


from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.turnos import TurnoBase

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
from personal.models import COLORES  # noqa: F401  (se usaba desde aquí)


class Config(models.Model):
    intervalo = models.PositiveSmallIntegerField(
        "cada cuánto se ofrecen horarios", default=15, choices=[(10, "Cada 10 minutos"), (15, "Cada 15 minutos"), (30, "Cada 30 minutos")],
        help_text="Ej.: con 15, los horarios libres son 10:00, 10:15, 10:30…")
    duracion = models.PositiveSmallIntegerField(
        "duración si el servicio no la tiene", default=30, validators=[MinValueValidator(5), MaxValueValidator(480)],
        help_text="Minutos. Cada servicio puede tener su propia duración (Productos → el servicio → Duración).")
    dias_compartir = models.PositiveSmallIntegerField(
        "días que se comparten", default=5, validators=[MinValueValidator(1), MaxValueValidator(14)],
        help_text="Cuántos días muestra el mensaje de «Compartir mis horarios».")

    class Meta:
        verbose_name = "configuración de citas"
        verbose_name_plural = "configuración de citas"

    def __str__(self):
        return "Configuración de citas"

    @classmethod
    def cargar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Horario(models.Model):
    profesional = models.ForeignKey("personal.Persona", on_delete=models.CASCADE, related_name="horarios")
    dia = models.PositiveSmallIntegerField(choices=list(enumerate(DIAS)))
    entrada = models.TimeField()
    salida = models.TimeField()
    descanso_desde = models.TimeField("refrigerio desde", null=True, blank=True)
    descanso_hasta = models.TimeField("refrigerio hasta", null=True, blank=True)

    class Meta:
        verbose_name = "horario"
        verbose_name_plural = "horarios"
        ordering = ["profesional", "dia"]
        constraints = [models.UniqueConstraint(fields=["profesional", "dia"], name="un_horario_por_dia")]

    def __str__(self):
        return f"{self.profesional} · {DIAS[self.dia]} {self.entrada:%H:%M}-{self.salida:%H:%M}"


class Ausencia(models.Model):
    """Día libre, vacaciones o permiso. Sin horas = todo el día; con horas = solo ese rato (ej.: entra tarde)."""

    profesional = models.ForeignKey("personal.Persona", on_delete=models.CASCADE, related_name="ausencias")
    desde = models.DateField()
    hasta = models.DateField()
    hora_desde = models.TimeField(null=True, blank=True)
    hora_hasta = models.TimeField(null=True, blank=True)
    motivo = models.CharField(max_length=80, blank=True, help_text="Ej.: vacaciones, día libre, cita médica.")

    class Meta:
        verbose_name = "ausencia"
        verbose_name_plural = "ausencias"
        ordering = ["desde"]

    def __str__(self):
        return f"{self.profesional} · {self.desde:%d/%m}–{self.hasta:%d/%m} {self.motivo}"

    @property
    def todo_el_dia(self):
        return not (self.hora_desde and self.hora_hasta)


class Cita(TurnoBase):
    """Cita con una persona del Personal. Lo común (cliente, nota, quién la tomó, estados) está en core.turnos.TurnoBase."""

    CAMPO_HORA = "inicio"

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Por confirmar"
        CONFIRMADA = "CON", "Confirmada"
        ATENDIDA = "ATE", "Atendida"
        NO_VINO = "NOV", "No vino"
        CANCELADA = "CAN", "Cancelada"

    ACTIVAS = (Estado.PENDIENTE, Estado.CONFIRMADA)
    OCUPAN = (Estado.PENDIENTE, Estado.CONFIRMADA, Estado.ATENDIDA)

    fecha = models.DateField()
    inicio = models.TimeField()
    fin = models.TimeField()
    profesional = models.ForeignKey("personal.Persona", on_delete=models.PROTECT, related_name="citas")
    servicio = models.ForeignKey("productos.Variante", on_delete=models.SET_NULL, null=True, blank=True, related_name="citas")
    servicio_nombre = models.CharField("servicio", max_length=120, blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                 help_text="Precio del servicio: el del catálogo al agendar y, al cobrarse, el que se cobró.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    sin_cita = models.BooleanField("sin cita", default=False, help_text="Cliente que llegó sin cita: lo registró quien lo atendió.")
    cobrada = models.BooleanField(default=False, help_text="El servicio ya se cobró (o se marcó como cobrado aparte).")
    venta = models.ForeignKey("ventas.Venta", on_delete=models.SET_NULL, null=True, blank=True, related_name="citas",
                              help_text="La venta en la que se cobró.")

    class Meta:
        verbose_name = "cita"
        verbose_name_plural = "citas"
        ordering = ["fecha", "inicio", "pk"]
        indexes = [models.Index(fields=["fecha", "profesional"]), models.Index(fields=["telefono"])]

    def __str__(self):
        return f"{self.nombre} · {self.servicio_nombre} · {self.fecha:%d/%m} {self.inicio:%H:%M} ({self.profesional})"

    @property
    def por_cobrar(self):
        return self.estado == self.Estado.ATENDIDA and not self.cobrada


    @property
    def minutos(self):
        return (self.fin.hour * 60 + self.fin.minute) - (self.inicio.hour * 60 + self.inicio.minute)

