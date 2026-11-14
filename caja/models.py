from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

CERO = Decimal("0")

# Billetes y monedas del Perú, para contar el cajón al cerrar
DENOMINACIONES = ["200", "100", "50", "20", "10", "5", "2", "1", "0.50", "0.20", "0.10"]


class SesionCaja(models.Model):
    """Un turno de caja: desde que el cajero la abre con su sencillo hasta que la cierra y cuenta el efectivo."""

    class Estado(models.TextChoices):
        ABIERTA = "ABI", "Abierta"
        CERRADA = "CER", "Cerrada"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cajas", verbose_name="cajero")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ABIERTA)
    abierta_en = models.DateTimeField(default=timezone.now)
    monto_inicial = models.DecimalField("monto inicial (sencillo)", max_digits=12, decimal_places=2, default=CERO,
                                        validators=[MinValueValidator(CERO)])
    nota_apertura = models.CharField(max_length=200, blank=True)
    # Lo que sigue se guarda al cerrar, para que el cierre no cambie después
    cerrada_en = models.DateTimeField(null=True, blank=True)
    cerrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    esperado = models.DecimalField("efectivo esperado", max_digits=12, decimal_places=2, null=True, blank=True)
    contado = models.DecimalField("efectivo contado", max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    conteo = models.JSONField("conteo por billetes", default=dict, blank=True)
    resumen = models.JSONField(default=dict, blank=True)
    nota_cierre = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "caja"
        verbose_name_plural = "cajas"
        ordering = ["-abierta_en"]
        constraints = [models.UniqueConstraint(fields=["usuario"], condition=Q(estado="ABI"), name="una_caja_abierta_por_usuario")]

    def __str__(self):
        return f"Caja {self.numero} · {self.usuario}"

    @property
    def numero(self):
        return f"{self.pk:05d}" if self.pk else "—"

    @property
    def abierta(self):
        return self.estado == self.Estado.ABIERTA

    @property
    def de_dias_anteriores(self):
        return self.abierta and timezone.localtime(self.abierta_en).date() < timezone.localdate()

    @classmethod
    def abierta_de(cls, usuario):
        if not getattr(usuario, "is_authenticated", False):
            return None
        return cls.objects.filter(usuario=usuario, estado=cls.Estado.ABIERTA).first()


class MovimientoCaja(models.Model):
    """Dinero que entra o sale del cajón sin ser una venta: pago a proveedor, gastos, sencillo, retiro del dueño…"""

    class Tipo(models.TextChoices):
        INGRESO = "ING", "Ingreso"
        EGRESO = "EGR", "Egreso"

    class Categoria(models.TextChoices):
        PROVEEDOR = "PRO", "Pago a proveedor"
        GASTO = "GAS", "Gasto del local (luz, limpieza, movilidad…)"
        PERSONAL = "PER", "Pago o adelanto a personal"
        RETIRO = "RET", "Retiro del dueño / depósito al banco"
        DEVOLUCION = "DEV", "Devolución a cliente"
        SENCILLO = "SEN", "Sencillo o aporte de efectivo"
        OTRO = "OTR", "Otro"

    sesion = models.ForeignKey(SesionCaja, on_delete=models.CASCADE, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    categoria = models.CharField("motivo", max_length=3, choices=Categoria.choices, default=Categoria.OTRO)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    concepto = models.CharField("detalle", max_length=150, help_text='Ej.: "Gaseosas a Distribuidora Lima, factura F001-45".')
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    automatico = models.BooleanField(default=False, help_text="Lo creó el sistema (por ejemplo, al anular una venta de otro turno).")

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.monto} · {self.concepto}"

    @property
    def signo(self):
        return 1 if self.tipo == self.Tipo.INGRESO else -1
