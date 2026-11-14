from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from .utils import TamanoMaximo


class AnioLectivo(models.Model):
    anio = models.PositiveSmallIntegerField("año", unique=True)
    nombre = models.CharField(
        "denominación",
        max_length=200,
        blank=True,
        help_text='Opcional. Ej.: "Año de la recuperación y consolidación de la economía peruana"',
    )
    fecha_inicio = models.DateField("inicio de clases")
    fecha_fin = models.DateField("fin de clases")
    activo = models.BooleanField(
        "año en curso",
        default=False,
        help_text="Solo un año puede estar en curso. Es el que se usa por defecto en todo el sistema.",
    )

    class Meta:
        verbose_name = "año lectivo"
        verbose_name_plural = "años lectivos"
        ordering = ["-anio"]
        constraints = [
            models.UniqueConstraint(
                fields=["activo"], condition=models.Q(activo=True), name="un_solo_anio_activo"
            ),
        ]

    def __str__(self):
        return str(self.anio)

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin <= self.fecha_inicio:
            raise ValidationError({"fecha_fin": "Debe ser posterior a la fecha de inicio."})

    def validate_constraints(self, exclude=None):
        # Al marcar un año como "en curso", save() desmarca el anterior,
        # así que no validamos esa restricción en el formulario.
        exclude = set(exclude or ()) | {"activo"}
        super().validate_constraints(exclude=exclude)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.activo:
                AnioLectivo.objects.filter(activo=True).exclude(pk=self.pk).update(activo=False)
            super().save(*args, **kwargs)

    @classmethod
    def actual(cls):
        """Año en curso, o el más reciente si ninguno está marcado."""
        return cls.objects.filter(activo=True).first() or cls.objects.first()


class Periodo(models.Model):
    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="periodos")
    numero = models.PositiveSmallIntegerField("número")
    nombre = models.CharField(max_length=50)
    fecha_inicio = models.DateField("inicio")
    fecha_fin = models.DateField("fin")
    notas_cerradas = models.BooleanField(
        "notas cerradas", default=False, help_text="Si está marcado, los docentes ya no pueden cambiar las notas de este periodo."
    )

    class Meta:
        verbose_name = "periodo"
        verbose_name_plural = "periodos"
        ordering = ["anio_lectivo", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["anio_lectivo", "numero"], name="periodo_unico_por_anio"),
        ]

    def __str__(self):
        return f"{self.nombre} {self.anio_lectivo}"

    @property
    def corto(self):
        """Ej.: "I Bimestre" -> "I B"."""
        partes = self.nombre.split()
        return f"{partes[0]} {partes[1][0]}" if len(partes) > 1 else self.nombre[:4]

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "Debe ser igual o posterior a la fecha de inicio."})


class Nivel(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "nivel"
        verbose_name_plural = "niveles"
        ordering = ["orden"]

    def __str__(self):
        return self.nombre


class Grado(models.Model):
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, related_name="grados")
    nombre = models.CharField(max_length=50, help_text='Ej.: "1er grado", "3 años"')
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "grado"
        verbose_name_plural = "grados"
        ordering = ["nivel__orden", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["nivel", "nombre"], name="grado_unico_por_nivel"),
        ]

    def __str__(self):
        return f"{self.nombre} de {self.nivel}"


class ModoAsistencia(models.TextChoices):
    DIARIA = "DIA", "Diaria (tutor)"
    POR_CURSO = "CUR", "Por curso (cada docente)"


class Seccion(models.Model):
    class Turno(models.TextChoices):
        MANANA = "M", "Mañana"
        TARDE = "T", "Tarde"

    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.PROTECT, related_name="secciones")
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name="secciones")
    nombre = models.CharField("sección", max_length=20, help_text='Ej.: "A", "B", "Única"')
    turno = models.CharField(max_length=1, choices=Turno.choices, default=Turno.MANANA)
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tutorias",
        limit_choices_to={"is_active": True},
    )
    vacantes = models.PositiveSmallIntegerField(default=30)
    modo_asistencia = models.CharField(
        "asistencia", max_length=3, choices=ModoAsistencia.choices, default=ModoAsistencia.DIARIA,
        help_text="Diaria: el tutor marca una vez al día. Por curso: cada docente marca en su clase.",
    )

    class Meta:
        verbose_name = "sección"
        verbose_name_plural = "secciones"
        ordering = ["anio_lectivo", "grado__nivel__orden", "grado__orden", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["anio_lectivo", "grado", "nombre"], name="seccion_unica"),
        ]

    def __str__(self):
        return f"{self.grado} \"{self.nombre}\""

    @property
    def por_curso(self):
        return self.modo_asistencia == ModoAsistencia.POR_CURSO

    @property
    def nombre_corto(self):
        return f"{self.grado.nombre} {self.nombre} · {self.grado.nivel}"


class DiaNoLectivo(models.Model):
    """Feriados, vacaciones y otros días sin clases. Puede ser un día o un rango."""

    class Tipo(models.TextChoices):
        FERIADO = "FER", "Feriado"
        VACACIONES = "VAC", "Vacaciones escolares"
        OTRO = "OTR", "Otro (jornada, día del maestro…)"

    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="dias_no_lectivos")
    fecha = models.DateField("desde")
    fecha_fin = models.DateField("hasta", null=True, blank=True, help_text="Déjalo vacío si es un solo día.")
    motivo = models.CharField(max_length=100)
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.FERIADO)

    class Meta:
        verbose_name = "día no lectivo"
        verbose_name_plural = "días no lectivos"
        ordering = ["fecha"]

    def __str__(self):
        return self.motivo

    def clean(self):
        if self.fecha_fin and self.fecha_fin < self.fecha:
            raise ValidationError({"fecha_fin": "Debe ser igual o posterior a la fecha de inicio."})

    @property
    def hasta(self):
        return self.fecha_fin or self.fecha

    @property
    def dias(self):
        return (self.hasta - self.fecha).days + 1

    @classmethod
    def mapa(cls, anio, desde=None, hasta=None, solo_feriados=False):
        """{fecha: motivo} de los días no lectivos (expande los rangos)."""
        from datetime import timedelta

        qs = cls.objects.filter(anio_lectivo=anio)
        if solo_feriados:
            qs = qs.filter(tipo=cls.Tipo.FERIADO)
        resultado = {}
        for d in qs:
            f = d.fecha
            while f <= d.hasta:
                if (desde is None or f >= desde) and (hasta is None or f <= hasta):
                    resultado[f] = d.motivo
                f += timedelta(days=1)
        return resultado

    @classmethod
    def motivo_de(cls, anio, fecha):
        if anio is None:
            return None
        d = cls.objects.filter(anio_lectivo=anio, fecha__lte=fecha).filter(
            models.Q(fecha_fin__gte=fecha) | models.Q(fecha_fin__isnull=True, fecha=fecha)
        ).first()
        return d.motivo if d else None


class Ajustes(models.Model):
    """Ajustes generales del sistema (una sola fila)."""

    modulos_inactivos = models.JSONField("módulos desactivados", default=list, blank=True)

    # --- Datos del colegio (Configuración → Datos del colegio) ---
    nombre = models.CharField("nombre del colegio", max_length=150, blank=True,
                              help_text='Como aparece en recibos y libretas. Ej.: "I.E.P. San Martín de Porres".')
    nombre_corto = models.CharField("nombre corto", max_length=30, blank=True,
                                    help_text="Para el menú y el ícono del celular. Ej.: «San Martín».")
    lema = models.CharField("lema o frase", max_length=150, blank=True)
    logo = models.ImageField("logo", upload_to="colegio/", blank=True, validators=[TamanoMaximo(5)],
                             help_text="PNG o JPG, de preferencia cuadrado y con fondo blanco o transparente.")
    ruc = models.CharField("RUC", max_length=11, blank=True)
    codigo_modular = models.CharField("código modular", max_length=20, blank=True)
    ugel = models.CharField("UGEL", max_length=60, blank=True)
    resolucion = models.CharField("resolución de creación", max_length=100, blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    distrito = models.CharField("distrito / ciudad", max_length=100, blank=True)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp del colegio", max_length=20, blank=True,
                                help_text="Se muestra en recibos y mensajes para que los padres respondan.")
    email = models.EmailField("correo", blank=True)
    web = models.URLField("página web o Facebook", blank=True)
    director = models.CharField("director(a)", max_length=150, blank=True, help_text="Nombre que firma las libretas.")
    nota_recibo = models.CharField("nota al pie del recibo", max_length=250, blank=True,
                                   help_text='Ej.: "Este recibo no es comprobante de pago SUNAT."')
    color = models.CharField("color principal", max_length=7, default="#0d6efd",
                             help_text="Color de la barra del celular cuando el sistema está instalado como app.")
    version_logo = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = "ajustes"
        verbose_name_plural = "ajustes"

    def __str__(self):
        return "Ajustes del sistema"

    @classmethod
    def cargar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # --- valores a mostrar (con respaldo en el .env si aún no se llenan) ---
    @property
    def nombre_mostrar(self):
        return self.nombre or settings.COLEGIO_NOMBRE

    @property
    def corto_mostrar(self):
        return self.nombre_corto or settings.COLEGIO_NOMBRE_CORTO

    def icono_url(self, tam=192):
        """Ícono cuadrado generado del logo; si no hay logo, el ícono del sistema."""
        from django.templatetags.static import static

        if self.logo and self.version_logo:
            return f"{settings.MEDIA_URL}colegio/icono-{tam}.png?v={self.version_logo}"
        return static({192: "img/icons/icon-192.png", 512: "img/icons/icon-512.png",
                       180: "img/icons/apple-touch-icon.png"}.get(tam, "img/icons/icon-192.png"))

    @property
    def icono_url_192(self):
        return self.icono_url(192)

    @property
    def icono_url_180(self):
        return self.icono_url(180)

    @property
    def logo_url(self):
        if self.logo and self.version_logo:
            return f"{settings.MEDIA_URL}colegio/logo.png?v={self.version_logo}"
        return self.icono_url(192)

    @property
    def tiene_logo(self):
        return bool(self.logo and self.version_logo)

    @property
    def whatsapp_link(self):
        import re

        d = re.sub(r"\D", "", self.whatsapp or "")
        if len(d) == 9 and d.startswith("9"):
            d = "51" + d
        return f"https://wa.me/{d}" if d else ""

    def linea_contacto(self):
        partes = [x for x in (self.direccion, self.distrito) if x]
        tel = " / ".join(x for x in (self.telefono, self.whatsapp) if x)
        if tel:
            partes.append(f"Telf. {tel}")
        return " · ".join(partes)

    def generar_iconos(self):
        """Del logo subido saca: logo.png (máx. 600 px) e íconos cuadrados 180/192/512 para el celular."""
        import os

        from PIL import Image, ImageOps

        carpeta = os.path.join(settings.MEDIA_ROOT, "colegio")
        os.makedirs(carpeta, exist_ok=True)
        with Image.open(self.logo.path) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
            # recorta bordes vacíos (transparentes o blancos)
            fondo = Image.new("RGBA", im.size, (255, 255, 255, 0))
            caja = Image.alpha_composite(fondo, im).getbbox()
            if caja:
                im = im.crop(caja)
            logo = im.copy()
            logo.thumbnail((600, 600))
            logo.save(os.path.join(carpeta, "logo.png"))
            for tam in (180, 192, 512):
                lienzo = Image.new("RGBA", (tam, tam), (255, 255, 255, 255))
                interior = int(tam * 0.84)
                copia = im.copy()
                copia.thumbnail((interior, interior), Image.LANCZOS)
                lienzo.alpha_composite(copia, ((tam - copia.width) // 2, (tam - copia.height) // 2))
                lienzo.convert("RGB").save(os.path.join(carpeta, f"icono-{tam}.png"))
        self.version_logo += 1


class PermisosRol(models.Model):
    """Permisos marcados para un rol (grupo de Django)."""

    grupo = models.OneToOneField("auth.Group", on_delete=models.CASCADE, related_name="permisos_sis")
    descripcion = models.CharField("descripción", max_length=150, blank=True)
    permisos = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "permisos de rol"
        verbose_name_plural = "permisos de roles"

    def __str__(self):
        return f"Permisos de {self.grupo.name}"
