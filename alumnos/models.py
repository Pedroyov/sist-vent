import re

from django.core.exceptions import ValidationError
from django.db import models

from core.utils import TamanoMaximo
from django.utils import timezone

from core.models import AnioLectivo, Seccion


class TipoDocumento(models.TextChoices):
    DNI = "DNI", "DNI"
    CE = "CE", "Carné de extranjería"
    PAS = "PAS", "Pasaporte"
    OTRO = "OTRO", "Otro"


def validar_documento(tipo, numero):
    if tipo == TipoDocumento.DNI and not re.fullmatch(r"\d{8}", numero or ""):
        raise ValidationError({"numero_documento": "El DNI debe tener 8 dígitos."})


class Persona(models.Model):
    tipo_documento = models.CharField("tipo de documento", max_length=4, choices=TipoDocumento.choices, default=TipoDocumento.DNI)
    numero_documento = models.CharField("N° de documento", max_length=15, unique=True)

    class Meta:
        abstract = True

    def clean(self):
        self.numero_documento = (self.numero_documento or "").strip().upper()
        validar_documento(self.tipo_documento, self.numero_documento)


class Apoderado(Persona):
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    celular = models.CharField(max_length=20, blank=True, help_text="Para llamadas y WhatsApp")
    celular2 = models.CharField("otro teléfono", max_length=20, blank=True)
    email = models.EmailField("correo", blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    ocupacion = models.CharField("ocupación", max_length=100, blank=True)

    class Meta:
        verbose_name = "apoderado"
        verbose_name_plural = "apoderados"
        ordering = ["apellidos", "nombres"]

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        return f"{self.apellidos}, {self.nombres}"

    @property
    def whatsapp(self):
        """Número en formato internacional para enlaces wa.me (Perú: 51)."""
        digitos = re.sub(r"\D", "", self.celular or "")
        if len(digitos) == 9 and digitos.startswith("9"):
            return "51" + digitos
        return digitos or None


class Alumno(Persona):
    class Sexo(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"

    codigo = models.CharField("código de estudiante", max_length=20, blank=True, help_text="Código SIAGIE (opcional)")
    apellido_paterno = models.CharField("apellido paterno", max_length=60)
    apellido_materno = models.CharField("apellido materno", max_length=60, blank=True)
    nombres = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField("fecha de nacimiento", null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=Sexo.choices, blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    foto = models.ImageField(upload_to="alumnos/fotos/", blank=True, validators=[TamanoMaximo(5)])
    observaciones = models.TextField(
        "observaciones de salud / otras", blank=True, help_text="Alergias, condiciones médicas, indicaciones especiales."
    )
    apoderados = models.ManyToManyField(Apoderado, through="AlumnoApoderado", related_name="alumnos")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "alumno"
        verbose_name_plural = "alumnos"
        ordering = ["apellido_paterno", "apellido_materno", "nombres"]

    def __str__(self):
        return self.nombre_completo

    @property
    def apellidos(self):
        return f"{self.apellido_paterno} {self.apellido_materno}".strip()

    @property
    def nombre_completo(self):
        return f"{self.apellidos}, {self.nombres}"

    @property
    def iniciales(self):
        return (self.nombres[:1] + self.apellido_paterno[:1]).upper()

    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None
        hoy = timezone.localdate()
        n = self.fecha_nacimiento
        return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))

    def matricula_en(self, anio):
        if anio is None:
            return None
        return self.matriculas.filter(anio_lectivo=anio).select_related("seccion__grado__nivel").first()

    @property
    def apoderado_principal(self):
        rel = self.vinculos.select_related("apoderado").order_by("-responsable_pago", "id").first()
        return rel.apoderado if rel else None


class AlumnoApoderado(models.Model):
    class Parentesco(models.TextChoices):
        PADRE = "PADRE", "Padre"
        MADRE = "MADRE", "Madre"
        ABUELO = "ABUELO", "Abuelo(a)"
        TIO = "TIO", "Tío(a)"
        HERMANO = "HERMANO", "Hermano(a)"
        TUTOR = "TUTOR", "Tutor legal"
        OTRO = "OTRO", "Otro"

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="vinculos")
    apoderado = models.ForeignKey(Apoderado, on_delete=models.CASCADE, related_name="vinculos")
    parentesco = models.CharField(max_length=10, choices=Parentesco.choices, default=Parentesco.MADRE)
    responsable_pago = models.BooleanField(
        "responsable de pagos", default=False, help_text="A esta persona se le enviarán los recordatorios de pago."
    )

    class Meta:
        verbose_name = "apoderado del alumno"
        verbose_name_plural = "apoderados del alumno"
        constraints = [
            models.UniqueConstraint(fields=["alumno", "apoderado"], name="apoderado_unico_por_alumno"),
        ]

    def __str__(self):
        return f"{self.apoderado} ({self.get_parentesco_display()}) de {self.alumno}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.responsable_pago:
            AlumnoApoderado.objects.filter(alumno=self.alumno).exclude(pk=self.pk).update(responsable_pago=False)


class Matricula(models.Model):
    class Estado(models.TextChoices):
        MATRICULADO = "MAT", "Matriculado"
        RETIRADO = "RET", "Retirado"
        TRASLADADO = "TRA", "Trasladado"

    class Tipo(models.TextChoices):
        NUEVO = "NUE", "Nuevo ingreso"
        RATIFICACION = "RAT", "Ratificación"

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="matriculas")
    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.PROTECT, related_name="matriculas")
    seccion = models.ForeignKey(Seccion, on_delete=models.PROTECT, related_name="matriculas", verbose_name="sección")
    fecha = models.DateField("fecha de matrícula", default=timezone.localdate)
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.NUEVO)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.MATRICULADO)
    fecha_retiro = models.DateField("fecha de retiro / traslado", null=True, blank=True)
    observacion = models.CharField("observación", max_length=200, blank=True)

    class Meta:
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"
        ordering = ["-anio_lectivo__anio"]
        constraints = [
            models.UniqueConstraint(fields=["alumno", "anio_lectivo"], name="una_matricula_por_anio"),
        ]

    def __str__(self):
        return f"{self.alumno} – {self.seccion.grado.nombre} {self.seccion.nombre} ({self.anio_lectivo})"

    def clean(self):
        if self.seccion_id and self.anio_lectivo_id and self.seccion.anio_lectivo_id != self.anio_lectivo_id:
            raise ValidationError({"seccion": "La sección no pertenece a ese año lectivo."})
        if self.estado != self.Estado.MATRICULADO and not self.fecha_retiro:
            self.fecha_retiro = timezone.localdate()
        if self.estado == self.Estado.MATRICULADO:
            self.fecha_retiro = None

    @property
    def activa(self):
        return self.estado == self.Estado.MATRICULADO
