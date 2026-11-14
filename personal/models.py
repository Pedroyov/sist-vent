from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

DIAS_LABORALES = [(1, "Lunes"), (2, "Martes"), (3, "Miércoles"), (4, "Jueves"), (5, "Viernes"), (6, "Sábado")]


class Trabajador(models.Model):
    class Cargo(models.TextChoices):
        DIRECCION = "DIR", "Dirección"
        DOCENTE = "DOC", "Docente"
        AUXILIAR = "AUX", "Auxiliar de educación"
        ADMINISTRATIVO = "ADM", "Administrativo / secretaría"
        TESORERIA = "TES", "Tesorería / caja"
        PSICOLOGIA = "PSI", "Psicología"
        LIMPIEZA = "LIM", "Limpieza / mantenimiento"
        SEGURIDAD = "SEG", "Portería / seguridad"
        OTRO = "OTR", "Otro"

    class Modalidad(models.TextChoices):
        MENSUAL = "MES", "Sueldo mensual fijo"
        POR_HORA = "HOR", "Pago por hora"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="trabajador",
        help_text="Cuenta con la que entra al sistema (opcional).",
    )
    numero_documento = models.CharField("DNI / documento", max_length=15, unique=True)
    apellidos = models.CharField(max_length=100)
    nombres = models.CharField(max_length=100)
    cargo = models.CharField(max_length=3, choices=Cargo.choices, default=Cargo.DOCENTE)
    especialidad = models.CharField(max_length=100, blank=True, help_text='Ej.: "Matemática", "Educación Primaria"')
    celular = models.CharField(max_length=20, blank=True)
    email = models.EmailField("correo", blank=True)
    fecha_ingreso = models.DateField("fecha de ingreso", null=True, blank=True)
    fecha_nacimiento = models.DateField("fecha de nacimiento", null=True, blank=True, help_text="Para recordar su cumpleaños en el inicio.")

    modalidad = models.CharField("modalidad de pago", max_length=3, choices=Modalidad.choices, default=Modalidad.MENSUAL)
    sueldo = models.DecimalField(
        "sueldo mensual (S/)", max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    pago_hora = models.DecimalField(
        "pago por hora (S/)", max_digits=8, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)],
        help_text="En docentes, por hora pedagógica de clase.",
    )
    horas_extra_semana = models.DecimalField(
        "otras horas por semana", max_digits=5, decimal_places=1, default=Decimal("0"),
        validators=[MinValueValidator(0)],
        help_text="Horas fuera del horario de clases que también se pagan (coordinación, tutoría, reuniones…).",
    )
    horas_max_semana = models.PositiveSmallIntegerField(
        "máximo de horas de clase por semana", null=True, blank=True,
        help_text="Según su contrato (horas pedagógicas). El sistema avisa si se le asignan más.",
    )
    cuenta_bancaria = models.CharField("banco y N° de cuenta", max_length=60, blank=True)
    observaciones = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "trabajador"
        verbose_name_plural = "personal"
        ordering = ["-activo", "apellidos", "nombres"]

    def __str__(self):
        return f"{self.apellidos}, {self.nombres}"

    @property
    def nombre_corto(self):
        return f"{self.nombres.split()[0] if self.nombres else ''} {self.apellidos.split()[0] if self.apellidos else ''}".strip()

    @property
    def es_docente(self):
        return self.cargo in (self.Cargo.DOCENTE, self.Cargo.DIRECCION) or (
            self.usuario_id and self.usuario.asignaciones.exists()
        )


class HorarioTrabajador(models.Model):
    """Horario semanal de trabajo fuera de las clases (o de personal no docente)."""

    trabajador = models.ForeignKey(Trabajador, on_delete=models.CASCADE, related_name="horarios")
    dia = models.PositiveSmallIntegerField(choices=DIAS_LABORALES)
    inicio = models.TimeField()
    fin = models.TimeField()

    class Meta:
        verbose_name = "horario de trabajo"
        verbose_name_plural = "horarios de trabajo"
        ordering = ["dia", "inicio"]

    def __str__(self):
        return f"{self.get_dia_display()} {self.inicio:%H:%M}–{self.fin:%H:%M}"

    @property
    def horas(self):
        m = (self.fin.hour * 60 + self.fin.minute) - (self.inicio.hour * 60 + self.inicio.minute)
        return Decimal(max(m, 0)) / 60
