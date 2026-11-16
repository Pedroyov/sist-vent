from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

CERO = Decimal("0")


class Cliente(models.Model):
    class TipoDocumento(models.TextChoices):
        DNI = "DNI", "DNI"
        RUC = "RUC", "RUC"
        CE = "CE", "Carné de extranjería"
        PAS = "PAS", "Pasaporte"
        SIN = "SD", "Sin documento"

    tipo_documento = models.CharField("documento", max_length=3, choices=TipoDocumento.choices, default=TipoDocumento.DNI)
    numero_documento = models.CharField("número", max_length=12, blank=True)
    nombre = models.CharField("nombre o razón social", max_length=150)
    telefono = models.CharField("celular / WhatsApp", max_length=20, blank=True)
    email = models.EmailField("correo", blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True, help_text="Para la factura (RUC) o delivery.")
    limite_credito = models.DecimalField("límite de fiado", max_digits=10, decimal_places=2, default=CERO,
                                         validators=[MinValueValidator(CERO)],
                                         help_text="Hasta cuánto puede deber. 0 = sin límite.")
    nota = models.CharField(max_length=200, blank=True)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["tipo_documento", "numero_documento"], condition=~Q(numero_documento=""),
                                               name="documento_cliente_unico")]

    def __str__(self):
        return self.nombre

    @property
    def documento(self):
        if not self.numero_documento:
            return ""
        return f"{self.get_tipo_documento_display() if self.tipo_documento in ('DNI', 'RUC') else self.tipo_documento} {self.numero_documento}"

    @property
    def total_fiado(self):
        from ventas.models import MetodoPago, Pago, Venta

        return Pago.objects.filter(venta__cliente=self, venta__estado=Venta.Estado.PAGADA, metodo=MetodoPago.CREDITO
                                   ).aggregate(t=Sum("monto"))["t"] or CERO

    @property
    def total_abonado(self):
        return self.abonos.filter(anulado=False).aggregate(t=Sum("monto"))["t"] or CERO

    @property
    def saldo(self):
        """Lo que debe ahora."""
        return (self.total_fiado - self.total_abonado).quantize(Decimal("0.01"))

    @property
    def whatsapp(self):
        from core.utils import numero_whatsapp

        return numero_whatsapp(self.telefono)


class Abono(models.Model):
    """Pago que hace un cliente a cuenta de lo que debe (fiado)."""

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="abonos")
    fecha = models.DateTimeField(default=timezone.now)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    metodo = models.CharField("método", max_length=3)
    referencia = models.CharField(max_length=60, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    sesion_caja = models.ForeignKey("caja.SesionCaja", on_delete=models.PROTECT, null=True, blank=True, related_name="abonos")
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    motivo_anulacion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "pago de deuda"
        verbose_name_plural = "pagos de deudas"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"Pago {self.numero} · {self.cliente}"

    @property
    def numero(self):
        return f"P-{self.pk:06d}"

    def get_metodo_display(self):
        from ventas.models import MetodoPago

        if self.metodo == "INC":
            return "Incobrable"
        return dict(MetodoPago.choices).get(self.metodo, self.metodo)
