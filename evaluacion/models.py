from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q

from academico.models import Asignacion, Curso
from alumnos.models import Alumno
from core.models import AnioLectivo, Nivel, Periodo, Seccion

LETRAS = ["AD", "A", "B", "C"]
VALOR_LETRA = {"AD": 4, "A": 3, "B": 2, "C": 1}


class Escala(models.TextChoices):
    VIGESIMAL = "VIG", "Numérica de 0 a 20"
    LITERAL = "LIT", "Literal (AD, A, B, C)"


class Competencia(models.Model):
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, related_name="competencias")
    nombre = models.CharField(max_length=250)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "competencia"
        verbose_name_plural = "competencias"
        ordering = ["curso", "orden", "id"]

    def __str__(self):
        return self.nombre

    @property
    def corto(self):
        return f"C{self.orden}" if self.orden else "C"


class ConfigEvaluacion(models.Model):
    """Cómo se califica en un nivel durante un año."""

    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="config_evaluacion")
    nivel = models.ForeignKey(Nivel, on_delete=models.CASCADE, related_name="config_evaluacion")
    escala = models.CharField(max_length=3, choices=Escala.choices, default=Escala.VIGESIMAL)
    por_competencia = models.BooleanField(
        "calificar por competencia", default=True,
        help_text="Si no se marca, se pone una sola nota por curso en cada periodo.",
    )
    nota_aprobatoria = models.PositiveSmallIntegerField(
        "nota aprobatoria (0–20)", default=11, validators=[MaxValueValidator(20)],
        help_text="Solo para la escala de 0 a 20. Las notas menores se muestran en rojo.",
    )
    comentarios = models.BooleanField("comentario del docente por curso", default=True)
    conducta = models.BooleanField("nota de conducta (la pone el tutor)", default=True)

    class Meta:
        verbose_name = "configuración de evaluación"
        verbose_name_plural = "configuraciones de evaluación"
        constraints = [models.UniqueConstraint(fields=["anio_lectivo", "nivel"], name="config_eval_unica")]

    def __str__(self):
        return f"{self.nivel} {self.anio_lectivo}: {self.get_escala_display()}"

    @property
    def vigesimal(self):
        return self.escala == Escala.VIGESIMAL

    @classmethod
    def de(cls, anio, nivel):
        """Configuración del nivel; si no existe la crea con valores por defecto."""
        defaults = {"escala": Escala.VIGESIMAL if nivel.nombre.lower() == "secundaria" else Escala.LITERAL}
        obj, _ = cls.objects.get_or_create(anio_lectivo=anio, nivel=nivel, defaults=defaults)
        return obj


class ValorMixin(models.Model):
    numero = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(20)])
    letra = models.CharField(max_length=2, blank=True, choices=[(x, x) for x in LETRAS])

    class Meta:
        abstract = True

    @property
    def valor(self):
        return self.numero if self.numero is not None else (self.letra or None)


class Nota(ValorMixin):
    """Calificación de un alumno en un curso, un periodo y (si aplica) una competencia."""

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="notas")
    asignacion = models.ForeignKey(Asignacion, on_delete=models.CASCADE, related_name="notas")
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, related_name="notas")
    competencia = models.ForeignKey(Competencia, on_delete=models.CASCADE, null=True, blank=True, related_name="notas")
    conclusion = models.TextField(
        "conclusión descriptiva", max_length=1000, blank=True,
        help_text="Obligatoria en el SIAGIE cuando el nivel de logro es C.",
    )
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "nota"
        verbose_name_plural = "notas"
        constraints = [
            models.UniqueConstraint(fields=["alumno", "asignacion", "periodo", "competencia"],
                                    condition=Q(competencia__isnull=False), name="nota_competencia_unica"),
            models.UniqueConstraint(fields=["alumno", "asignacion", "periodo"],
                                    condition=Q(competencia__isnull=True), name="nota_curso_unica"),
        ]


class Comentario(models.Model):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="comentarios_notas")
    asignacion = models.ForeignKey(Asignacion, on_delete=models.CASCADE, related_name="comentarios")
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, related_name="comentarios")
    texto = models.TextField(max_length=600)

    class Meta:
        verbose_name = "comentario del docente"
        verbose_name_plural = "comentarios del docente"
        constraints = [models.UniqueConstraint(fields=["alumno", "asignacion", "periodo"], name="comentario_unico")]


class Conducta(ValorMixin):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="conductas")
    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, related_name="conductas")
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, related_name="conductas")
    comentario = models.TextField(max_length=600, blank=True)

    class Meta:
        verbose_name = "conducta"
        verbose_name_plural = "conductas"
        constraints = [models.UniqueConstraint(fields=["alumno", "periodo"], name="conducta_unica")]


# --- Cálculos ---------------------------------------------------------------

def promedio_vigesimal(numeros):
    numeros = [n for n in numeros if n is not None]
    if not numeros:
        return None
    return int((Decimal(sum(numeros)) / len(numeros)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def letra_final(letras):
    """Escala literal: el logro del final del periodo/año es el último registrado."""
    letras = [x for x in letras if x]
    return letras[-1] if letras else None
