from django.conf import settings
from django.db import models

from core.models import Nivel, Seccion


class Curso(models.Model):
    """Área o curso que se dicta en un nivel (Matemática, Comunicación…)."""

    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, related_name="cursos")
    nombre = models.CharField(max_length=100)
    abreviatura = models.CharField(max_length=10, blank=True, help_text='Para reportes. Ej.: "MAT"')
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True, help_text="Desmarca si ya no se dicta (no se borra el historial).")

    class Meta:
        verbose_name = "curso"
        verbose_name_plural = "cursos"
        ordering = ["nivel__orden", "orden", "nombre"]
        constraints = [models.UniqueConstraint(fields=["nivel", "nombre"], name="curso_unico_por_nivel")]

    def __str__(self):
        return self.nombre

    @property
    def corto(self):
        return self.abreviatura or self.nombre[:3].upper()


class Asignacion(models.Model):
    """Qué docente dicta qué curso en qué sección (la sección ya pertenece a un año)."""

    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, related_name="asignaciones")
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="asignaciones")
    docente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asignaciones"
    )

    class Meta:
        verbose_name = "asignación"
        verbose_name_plural = "asignaciones"
        ordering = ["seccion", "curso__orden", "curso__nombre"]
        constraints = [models.UniqueConstraint(fields=["seccion", "curso"], name="curso_unico_por_seccion")]

    def __str__(self):
        return f"{self.curso} – {self.seccion}"


DIAS_SEMANA = [(1, "Lunes"), (2, "Martes"), (3, "Miércoles"), (4, "Jueves"), (5, "Viernes")]


class HorasPlan(models.Model):
    """Plan de estudios: horas semanales de un curso en un grado, para un año."""

    anio_lectivo = models.ForeignKey("core.AnioLectivo", on_delete=models.CASCADE, related_name="plan_horas")
    grado = models.ForeignKey("core.Grado", on_delete=models.CASCADE, related_name="plan_horas")
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, related_name="plan_horas")
    horas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "horas del plan de estudios"
        verbose_name_plural = "plan de estudios"
        constraints = [models.UniqueConstraint(fields=["anio_lectivo", "grado", "curso"], name="horas_plan_unicas")]


class Bloque(models.Model):
    """Una hora de clase o un recreo dentro de la jornada de un nivel."""

    class Tipo(models.TextChoices):
        CLASE = "CLA", "Clase"
        RECREO = "REC", "Recreo"

    anio_lectivo = models.ForeignKey("core.AnioLectivo", on_delete=models.CASCADE, related_name="bloques")
    nivel = models.ForeignKey(Nivel, on_delete=models.CASCADE, related_name="bloques")
    orden = models.PositiveSmallIntegerField()
    inicio = models.TimeField()
    fin = models.TimeField()
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.CLASE)

    class Meta:
        verbose_name = "bloque horario"
        verbose_name_plural = "jornada (bloques horarios)"
        ordering = ["anio_lectivo", "nivel__orden", "orden"]

    def __str__(self):
        return f"{self.inicio:%H:%M}–{self.fin:%H:%M}"

    @property
    def minutos(self):
        return (self.fin.hour * 60 + self.fin.minute) - (self.inicio.hour * 60 + self.inicio.minute)

    @property
    def es_recreo(self):
        return self.tipo == self.Tipo.RECREO

    def se_cruza_con(self, otro):
        return self.inicio < otro.fin and otro.inicio < self.fin


class Clase(models.Model):
    """Una celda del horario: en esta sección, este día y bloque, se dicta este curso."""

    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, related_name="clases")
    dia = models.PositiveSmallIntegerField(choices=DIAS_SEMANA)
    bloque = models.ForeignKey(Bloque, on_delete=models.CASCADE, related_name="clases")
    asignacion = models.ForeignKey(Asignacion, on_delete=models.CASCADE, related_name="clases")

    class Meta:
        verbose_name = "clase del horario"
        verbose_name_plural = "horario de clases"
        constraints = [models.UniqueConstraint(fields=["seccion", "dia", "bloque"], name="una_clase_por_celda")]

    def __str__(self):
        return f"{self.get_dia_display()} {self.bloque} – {self.asignacion}"
