"""Facturación electrónica: boletas, facturas y notas de crédito que se envían a SUNAT por medio de un proveedor."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

CERO = Decimal("0")


class Config(models.Model):
    """Configuración de la facturación (una sola fila)."""

    class Proveedor(models.TextChoices):
        PRUEBA = "PRU", "Prueba: simula a SUNAT (no tiene valor tributario)"
        NUBEFACT = "NUB", "Nubefact"

    class Afectacion(models.TextChoices):
        GRAVADO = "G", "Gravado con IGV (lo normal)"
        EXONERADO = "E", "Exonerado (por ejemplo, Amazonía)"
        INAFECTO = "I", "Inafecto"

    proveedor = models.CharField(max_length=3, choices=Proveedor.choices, default=Proveedor.PRUEBA)
    ruta = models.URLField("ruta de la API", blank=True, help_text="La da el proveedor (en Nubefact: opción API - Integración).")
    token = models.CharField(max_length=200, blank=True, help_text="Clave de la API. No la compartas.")
    igv = models.DecimalField("IGV %", max_digits=5, decimal_places=2, default=Decimal("18"),
                              validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("50"))],
                              help_text="Lo normal es 18. Cámbialo solo si tu contador te indica otra tasa.")
    afectacion = models.CharField("los precios están", max_length=1, choices=Afectacion.choices, default=Afectacion.GRAVADO)
    serie_boleta = models.CharField(max_length=4, default="B001")
    serie_factura = models.CharField(max_length=4, default="F001")
    serie_nc_boleta = models.CharField("serie de notas de crédito de boletas", max_length=4, default="BC01")
    serie_nc_factura = models.CharField("serie de notas de crédito de facturas", max_length=4, default="FC01")
    por_defecto = models.CharField("al cobrar, proponer", max_length=1, default="B",
                                   choices=[("N", "Nota de venta (sin comprobante)"), ("B", "Boleta"), ("F", "Factura")])

    class Meta:
        verbose_name = "configuración de facturación"

    @classmethod
    def cargar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def lista(self):
        """¿Se puede emitir de verdad? (en modo prueba siempre)."""
        return self.proveedor == self.Proveedor.PRUEBA or bool(self.ruta and self.token)


class Serie(models.Model):
    """Correlativo de cada serie (B001, F001…). Se bloquea al numerar para no repetir números."""
    codigo = models.CharField(max_length=4, unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.codigo} ({self.ultimo})"


class Comprobante(models.Model):
    class Tipo(models.TextChoices):
        FACTURA = "01", "Factura electrónica"
        BOLETA = "03", "Boleta de venta electrónica"
        NOTA_CREDITO = "07", "Nota de crédito electrónica"

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Pendiente de envío"
        ENVIADO = "ENV", "Enviado, esperando a SUNAT"
        ACEPTADO = "ACE", "Aceptado por SUNAT"
        RECHAZADO = "REC", "Rechazado"

    venta = models.ForeignKey("ventas.Venta", on_delete=models.PROTECT, related_name="comprobantes")
    tipo = models.CharField(max_length=2, choices=Tipo.choices)
    serie = models.CharField(max_length=4)
    numero = models.PositiveIntegerField()
    fecha = models.DateField()
    # cliente: 6 RUC, 1 DNI, 4 carné de extranjería, 7 pasaporte, - varios (sin documento)
    cliente_tipo_doc = models.CharField(max_length=1, default="-")
    cliente_doc = models.CharField(max_length=15, blank=True)
    cliente_nombre = models.CharField(max_length=150, blank=True)
    cliente_direccion = models.CharField(max_length=200, blank=True)
    igv_pct = models.DecimalField(max_digits=5, decimal_places=2)
    gravada = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    exonerada = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    inafecta = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    igv = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    detalle = models.JSONField(default=list, help_text="Líneas tal como se enviaron.")
    modifica = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="notas",
                                 help_text="Para notas de crédito: el comprobante que anula.")
    motivo = models.CharField(max_length=200, blank=True)
    # respuesta del proveedor
    proveedor = models.CharField(max_length=3)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    mensaje = models.CharField(max_length=500, blank=True)
    enlace_pdf = models.URLField(max_length=500, blank=True)
    enlace_xml = models.URLField(max_length=500, blank=True)
    hash = models.CharField(max_length=100, blank=True)
    qr = models.CharField("texto del código QR", max_length=500, blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    enviado_en = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "comprobante"
        verbose_name_plural = "comprobantes"
        ordering = ["-creado", "-id"]
        constraints = [models.UniqueConstraint(fields=["serie", "numero"], name="comprobante_serie_numero_unico")]

    def __str__(self):
        return self.numero_str

    @property
    def numero_str(self):
        return f"{self.serie}-{self.numero:08d}"

    @property
    def es_nota(self):
        return self.tipo == self.Tipo.NOTA_CREDITO

    @property
    def prueba(self):
        return self.proveedor == Config.Proveedor.PRUEBA

    @property
    def anulado(self):
        return self.notas.exclude(estado=self.Estado.RECHAZADO).exists()

    @property
    def nombre_impreso(self):
        """Como va en la representación impresa."""
        return {"01": "FACTURA ELECTRÓNICA", "03": "BOLETA DE VENTA ELECTRÓNICA", "07": "NOTA DE CRÉDITO ELECTRÓNICA"}[self.tipo]
