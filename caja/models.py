from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

CERO = Decimal("0")

# Billetes y monedas del Perú, para contar el cajón al cerrar
DENOMINACIONES = ["200", "100", "50", "20", "10", "5", "2", "1", "0.50", "0.20", "0.10"]


class PuntoCaja(models.Model):
    """Una caja física o punto de cobro (Caja 1, Barra). Puede tener sus propias series de boletas y facturas;
    vacías = las generales de Facturación."""

    nombre = models.CharField(max_length=40, unique=True, help_text='Ej.: "Caja 1", "Barra", "Segundo piso".')
    serie_boleta = models.CharField("serie de boletas", max_length=4, blank=True)
    serie_factura = models.CharField("serie de facturas", max_length=4, blank=True)
    serie_nc_boleta = models.CharField("serie de notas de crédito de boletas", max_length=4, blank=True)
    serie_nc_factura = models.CharField("serie de notas de crédito de facturas", max_length=4, blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "caja (punto de cobro)"
        verbose_name_plural = "cajas (puntos de cobro)"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def serie(self, campo, config):
        """La serie de este punto para `campo` (serie_boleta…), o la general si no tiene."""
        return getattr(self, campo) or getattr(config, campo)


class SesionCaja(models.Model):
    """Un turno de caja: desde que el cajero la abre con su sencillo hasta que la cierra y cuenta el efectivo."""

    class Estado(models.TextChoices):
        ABIERTA = "ABI", "Abierta"
        CERRADA = "CER", "Cerrada"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cajas", verbose_name="cajero")
    punto = models.ForeignKey(PuntoCaja, on_delete=models.PROTECT, null=True, blank=True, related_name="sesiones", verbose_name="caja")
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
    queda = models.DecimalField("dejado en el cajón", max_digits=12, decimal_places=2, null=True, blank=True,
                                help_text="Sencillo que se dejó para el siguiente turno; lo demás se retiró al cerrar.")
    conteo = models.JSONField("conteo por billetes", default=dict, blank=True)
    resumen = models.JSONField(default=dict, blank=True)
    nota_cierre = models.CharField(max_length=300, blank=True)
    # Cierre ciego: si el primer conteo no cuadraba, se pidió volver a contar y aquí queda el primero.
    primer_conteo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Una caja cerrada no se reabre; Administración puede corregir lo contado con motivo. Se guarda el conteo original.
    contado_original = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    corregido_en = models.DateTimeField(null=True, blank=True)
    corregido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    motivo_correccion = models.CharField(max_length=200, blank=True)
    # Cada vez que Administración reabre la caja, el cierre anterior se guarda aquí (con quién, cuándo y por qué).
    reaperturas = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "caja"
        verbose_name_plural = "cajas"
        ordering = ["-abierta_en"]
        constraints = [models.UniqueConstraint(fields=["usuario"], condition=Q(estado="ABI"), name="una_caja_abierta_por_usuario")]
        indexes = [models.Index(fields=["cerrada_en"])]

    def __str__(self):
        return f"Caja {self.numero} · {self.usuario}"

    @property
    def numero(self):
        return f"{self.pk:05d}" if self.pk else "—"

    @property
    def abierta(self):
        return self.estado == self.Estado.ABIERTA

    @property
    def retirado(self):
        """Lo que se sacó del cajón al cerrar (lo contado menos lo que se dejó)."""
        if self.contado is None or self.queda is None:
            return None
        return self.contado - self.queda

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
        GASTO = "GAS", "Gasto del local (alquiler, luz, limpieza, movilidad…)"
        PERSONAL = "PER", "Pago o adelanto a personal"
        RETIRO = "RET", "Retiro del dueño / depósito al banco"
        DEVOLUCION = "DEV", "Devolución a cliente"
        SENCILLO = "SEN", "Sencillo o aporte de efectivo"
        OTRO = "OTR", "Otro"

    # Sin caja = «fuera de caja»: un gasto pagado por transferencia, Yape o con dinero que no estaba en el cajón (alquiler, sueldo).
    sesion = models.ForeignKey(SesionCaja, on_delete=models.CASCADE, related_name="movimientos", null=True, blank=True)
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    categoria = models.CharField("motivo", max_length=3, choices=Categoria.choices, default=Categoria.OTRO)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    concepto = models.CharField("detalle", max_length=150, help_text='Ej.: "Gaseosas a Distribuidora Lima, factura F001-45".')
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    automatico = models.BooleanField(default=False, help_text="Lo creó el sistema (por ejemplo, al anular una venta de otro turno).")
    despues_del_cierre = models.BooleanField(default=False, help_text="Salida olvidada: Administración la agregó con la caja ya cerrada.")
    # Solo los gastos fuera de caja se anulan (los de una caja quedan en su cierre); no se borran: queda quién y por qué.
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    motivo_anulacion = models.CharField("motivo de la anulación", max_length=200, blank=True)
    compra = models.ForeignKey("compras.Compra", on_delete=models.PROTECT, null=True, blank=True, related_name="pagos",
                               help_text="Pago de una compra registrada (módulo Compras).")
    persona = models.ForeignKey("personal.Persona", on_delete=models.SET_NULL, null=True, blank=True, related_name="pagos",
                                verbose_name="a quién", help_text="Pagos y adelantos al personal (función «Pagos al personal»).")

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["fecha"])]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.monto} · {self.concepto}"

    @property
    def motivo(self):
        """El motivo sin la explicación entre paréntesis: «Gasto del local»."""
        return self.get_categoria_display().split(" (")[0]

    @property
    def fuera_de_caja(self):
        return self.sesion_id is None

    @property
    def es_gasto(self):
        """Cuenta como gasto del negocio: no lo es un retiro del dueño ni lo que el sistema devolvió al anular un cobro."""
        return self.tipo == self.Tipo.EGRESO and not self.automatico and not self.anulado and self.categoria != self.Categoria.RETIRO

    @property
    def signo(self):
        return 1 if self.tipo == self.Tipo.INGRESO else -1
