from django.conf import settings
from django.db import models
from django.db.models import Q

from academico.models import Asignacion
from alumnos.models import Alumno
from core.models import Seccion


class Sesion(models.Model):
    """Una toma de asistencia: una sección en una fecha (y un curso, si es por curso)."""

    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, related_name="sesiones_asistencia")
    fecha = models.DateField()
    asignacion = models.ForeignKey(
        Asignacion, on_delete=models.CASCADE, null=True, blank=True, related_name="sesiones",
        help_text="Vacío = asistencia diaria de la sección.",
    )
    tomado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sesiones_asistencia")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "toma de asistencia"
        verbose_name_plural = "tomas de asistencia"
        ordering = ["-fecha"]
        constraints = [
            models.UniqueConstraint(fields=["seccion", "fecha"], condition=Q(asignacion__isnull=True), name="una_diaria_por_seccion_fecha"),
            models.UniqueConstraint(fields=["asignacion", "fecha"], condition=Q(asignacion__isnull=False), name="una_por_curso_fecha"),
        ]

    def __str__(self):
        curso = f" · {self.asignacion.curso}" if self.asignacion_id else ""
        return f"{self.seccion}{curso} – {self.fecha:%d/%m/%Y}"


class Estado(models.TextChoices):
    PRESENTE = "P", "Presente"
    TARDE = "T", "Tardanza"
    FALTA = "F", "Falta"
    JUSTIFICADA = "J", "Falta justificada"


class Asistencia(models.Model):
    sesion = models.ForeignKey(Sesion, on_delete=models.CASCADE, related_name="registros")
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="asistencias")
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.PRESENTE)
    observacion = models.CharField("observación", max_length=200, blank=True)

    class Meta:
        verbose_name = "asistencia"
        verbose_name_plural = "asistencias"
        constraints = [models.UniqueConstraint(fields=["sesion", "alumno"], name="asistencia_unica")]

    def __str__(self):
        return f"{self.alumno} – {self.get_estado_display()}"


class AvisoFalta(models.Model):
    """Registro de que se avisó al apoderado de una falta (por WhatsApp)."""

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="avisos_falta")
    fecha = models.DateField()
    enviado = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "aviso de falta"
        verbose_name_plural = "avisos de falta"
