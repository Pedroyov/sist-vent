from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

CERO = Decimal("0")


class Correlativo(models.Model):
    """Contador para numerar documentos sin saltos ni repetidos (se bloquea la fila al usarlo)."""

    nombre = models.CharField(max_length=30, unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.nombre}: {self.ultimo}"

    @classmethod
    def siguiente(cls, nombre):
        """Debe llamarse dentro de transaction.atomic()."""
        c, _ = cls.objects.select_for_update().get_or_create(nombre=nombre)
        c.ultimo += 1
        c.save(update_fields=["ultimo"])
        return c.ultimo


class MetodoPago(models.TextChoices):
    EFECTIVO = "EFE", "Efectivo"
    YAPE = "YAP", "Yape"
    PLIN = "PLI", "Plin"
    TARJETA = "TAR", "Tarjeta"
    TRANSFERENCIA = "TRA", "Transferencia"
    CREDITO = "CRE", "Fiado"


class Venta(models.Model):
    class Estado(models.TextChoices):
        PAGADA = "PAG", "Pagada"
        ANULADA = "ANU", "Anulada"

    numero = models.PositiveIntegerField("número", unique=True)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PAGADA)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventas",
                                verbose_name="vendedor")
    atendio = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                verbose_name="mozo", help_text="Quien atendió la mesa (si no es quien cobró).")
    sesion_caja = models.ForeignKey("caja.SesionCaja", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="ventas", verbose_name="caja")
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, null=True, blank=True, related_name="ventas")
    cliente_nombre = models.CharField("cliente", max_length=150, blank=True)
    cliente_documento = models.CharField("DNI / RUC", max_length=11, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    propina = models.DecimalField(max_digits=12, decimal_places=2, default=CERO,
                                  help_text="No es parte de la venta: se cobra aparte y va en los pagos.")
    recibido = models.DecimalField("efectivo recibido", max_digits=12, decimal_places=2, null=True, blank=True)
    vuelto = models.DecimalField(max_digits=12, decimal_places=2, default=CERO)
    nota = models.CharField(max_length=200, blank=True)
    token = models.CharField(max_length=40, unique=True, null=True, blank=True,
                             help_text="Evita registrar dos veces la misma venta si se pulsa dos veces «Cobrar».")
    anulada_en = models.DateTimeField(null=True, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    motivo_anulacion = models.CharField("motivo", max_length=200, blank=True)

    class Meta:
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-fecha", "-numero"]

    def __str__(self):
        return f"Venta {self.numero_str}"

    @property
    def numero_str(self):
        return f"{self.numero:06d}"

    @property
    def anulada(self):
        return self.estado == self.Estado.ANULADA

    @property
    def fiado(self):
        return sum((p.monto for p in self.pagos.all() if p.metodo == MetodoPago.CREDITO), CERO)

    @property
    def ganancia(self):
        return self.total - self.costo_total

    @property
    def costo_total(self):
        return sum((i.costo_unitario * i.cantidad for i in self.items.all() if i.costo_unitario is not None), CERO)


class VentaItem(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="items")
    variante = models.ForeignKey("productos.Variante", on_delete=models.PROTECT, related_name="ventas")
    descripcion = models.CharField(max_length=240, help_text="Nombre al momento de la venta (por si luego cambia).")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    precio_lista = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio del catálogo en ese momento.")
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    opciones = models.JSONField(default=list, blank=True, help_text="Opciones elegidas (término, adicionales…) como estaban al vender.")

    class Meta:
        verbose_name = "ítem de venta"
        verbose_name_plural = "ítems de venta"
        ordering = ["id"]

    def __str__(self):
        return f"{self.cantidad} × {self.descripcion}"

    @property
    def precio_cambiado(self):
        return self.precio_unitario != self.precio_lista


class Pago(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="pagos")
    metodo = models.CharField("método", max_length=3, choices=MetodoPago.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2, help_text="Lo que se queda el negocio (sin el vuelto).")
    referencia = models.CharField(max_length=60, blank=True, help_text="N° de operación de Yape, voucher, etc.")

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_metodo_display()} {self.monto}"
