"""Impresión automática: una cola en el servidor y una estación (la PC de caja con Chrome en «kiosk-printing»).

Cualquier equipo (celular, tablet, PC) solo deja trabajos en la cola al vender, enviar a cocina o cerrar la caja; la
estación los toma uno por uno (con bloqueo: cada trabajo lo toma una sola estación) y los imprime sin cuadros. Si la
ticketera o la PC fallan, el trabajo queda en la cola para reimprimir. La lógica está en impresion/servicios.py."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Trabajo(models.Model):
    class Tipo(models.TextChoices):
        TICKET = "TIC", "Ticket de venta"
        COMANDA = "COM", "Comanda"
        PRECUENTA = "PRE", "Precuenta"
        CIERRE = "CIE", "Cierre de caja"
        OTRO = "OTR", "Otro"

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "En cola"
        TOMADO = "TOM", "Imprimiendo"
        IMPRESO = "IMP", "Impreso"
        ERROR = "ERR", "No se pudo imprimir"

    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    url = models.CharField(max_length=300, help_text="Lo que se imprime (la misma página del botón Imprimir).")
    descripcion = models.CharField(max_length=120)
    copia = models.BooleanField(default=False, help_text="Reimpresión pedida a mano.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(default=timezone.now, db_index=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    tomado_en = models.DateTimeField(null=True, blank=True)
    estacion = models.ForeignKey("Estacion", on_delete=models.SET_NULL, null=True, blank=True, related_name="trabajos")
    impreso_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "trabajo de impresión"
        verbose_name_plural = "cola de impresión"
        ordering = ["creado", "id"]

    def __str__(self):
        return self.descripcion


class Estacion(models.Model):
    """La PC que imprime. Avisa cada pocos segundos que sigue viva (si no, el Inicio avisa que no responde)."""

    clave = models.CharField(max_length=40, unique=True)
    nombre = models.CharField(max_length=60, default="Caja")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    ultimo_latido = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "estación de impresión"
        verbose_name_plural = "estaciones de impresión"

    def __str__(self):
        return self.nombre
