"""Compras: proveedores, la factura o boleta que entregan y lo que se les debe.

Una compra se registra una sola vez: sus líneas con producto suman stock por el kardex (y ajustan el costo por promedio
ponderado); sus líneas libres (insumos, fletes) son gasto del periodo. Los pagos no tienen tabla propia: son egresos de
caja (`caja.MovimientoCaja`, motivo «Pago a proveedor») ligados a la compra, de una caja abierta o fuera de caja.
Lo que falta pagar se calcula: total menos pagos no anulados. Todo esto es el módulo «compras»; sin él, el stock sigue
entrando por Productos → Ingreso y el pago a proveedor es un egreso suelto, como siempre.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

CERO = Decimal("0")


class Proveedor(models.Model):
    ruc = models.CharField("RUC o DNI", max_length=11, blank=True)
    nombre = models.CharField("razón social o nombre", max_length=150)
    comercial = models.CharField("nombre comercial", max_length=100, blank=True, help_text="Como lo conoces: «Distribuidora Lima».")
    contacto = models.CharField(max_length=80, blank=True, help_text="Con quién hablas (vendedor, reparto).")
    telefono = models.CharField("celular / WhatsApp", max_length=20, blank=True)
    email = models.EmailField("correo", blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    plazo = models.PositiveSmallIntegerField("plazo habitual (días)", default=0,
                                            help_text="Días que da para pagar al crédito. 0 = se paga al contado.")
    nota = models.CharField(max_length=200, blank=True)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["ruc"], condition=~Q(ruc=""), name="ruc_proveedor_unico")]

    def __str__(self):
        return self.comercial or self.nombre


class Compra(models.Model):
    class Documento(models.TextChoices):
        FACTURA = "FAC", "Factura"
        BOLETA = "BOL", "Boleta"
        NOTA = "NV", "Nota de venta"
        SIN = "SIN", "Sin documento"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="compras")
    documento = models.CharField(max_length=3, choices=Documento.choices, default=Documento.FACTURA)
    serie = models.CharField(max_length=4, blank=True)
    numero = models.CharField("número", max_length=12, blank=True)
    fecha = models.DateField(default=timezone.localdate)
    vence = models.DateField("vence", null=True, blank=True, help_text="Solo al crédito: hasta cuándo hay que pagar.")
    base = models.DecimalField("valor sin IGV", max_digits=12, decimal_places=2, default=CERO)
    igv = models.DecimalField("IGV", max_digits=12, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)
    token = models.CharField(max_length=40, unique=True, null=True, blank=True, help_text="Evita registrarla dos veces con doble clic.")
    anulada = models.BooleanField(default=False)
    anulada_en = models.DateTimeField(null=True, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    motivo_anulacion = models.CharField("motivo", max_length=200, blank=True)

    class Meta:
        verbose_name = "compra"
        verbose_name_plural = "compras"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["fecha"]), models.Index(fields=["vence"])]

    def __str__(self):
        return f"{self.documento_str} · {self.proveedor}"

    @property
    def documento_str(self):
        numero = "-".join(x for x in (self.serie, self.numero) if x)
        return f"{self.get_documento_display()} {numero}".strip()

    @property
    def referencia(self):
        """Lo que se anota en el kardex y en el egreso de caja."""
        return f"Compra {'-'.join(x for x in (self.serie, self.numero) if x) or self.pk}"[:60]

    @property
    def pagado(self):
        if hasattr(self, "_pagado"):
            total = self._pagado or CERO
        else:
            total = self.pagos.filter(anulado=False).aggregate(t=Sum("monto"))["t"] or CERO
        return Decimal(total).quantize(Decimal("0.01"))  # SQLite devuelve las sumas con decimales de más

    @property
    def saldo(self):
        return CERO if self.anulada else max(CERO, self.total - self.pagado)

    @property
    def vencida(self):
        return bool(self.saldo and self.vence and self.vence < timezone.localdate())

    @property
    def estado(self):
        if self.anulada:
            return "Anulada"
        if not self.saldo:
            return "Pagada"
        return "Vencida" if self.vencida else "Por pagar"


class CompraItem(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="items")
    variante = models.ForeignKey("productos.Variante", on_delete=models.PROTECT, null=True, blank=True, related_name="compras",
                                 help_text="Vacío = línea libre (insumo, flete): no mueve stock y es gasto.")
    descripcion = models.CharField(max_length=200)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=4)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    costo_antes = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True,
                                      help_text="El costo que tenía antes de esta compra (para sugerir el precio si subió).")

    class Meta:
        verbose_name = "línea de compra"
        verbose_name_plural = "líneas de compra"
        ordering = ["id"]

    def __str__(self):
        return f"{self.cantidad.normalize():f} × {self.descripcion}"

    @property
    def libre(self):
        return self.variante_id is None
