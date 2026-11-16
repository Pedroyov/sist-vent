from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

CERO = Decimal("0")


class Zona(models.Model):
    nombre = models.CharField(max_length=40, unique=True, help_text='Ej.: "Salón", "Terraza", "Segundo piso".')
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "zona"
        verbose_name_plural = "zonas"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Mesa(models.Model):
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="mesas")
    nombre = models.CharField(max_length=20, unique=True, help_text='Número o nombre corto: "1", "T2", "Barra 1".')
    capacidad = models.PositiveSmallIntegerField(default=4)
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)
    unida_a = models.ForeignKey("Cuenta", on_delete=models.SET_NULL, null=True, blank=True, related_name="mesas_unidas",
                                help_text="Mesa pegada a la de otra cuenta (familias, grupos). Cuenta como ocupada mientras esa cuenta siga abierta.")

    class Meta:
        verbose_name = "mesa"
        verbose_name_plural = "mesas"
        ordering = ["zona__orden", "orden", "nombre"]

    def __str__(self):
        return f"Mesa {self.nombre}"


class Cuenta(models.Model):
    """Lo que va consumiendo una mesa (o un pedido para llevar) hasta que se cobra."""

    class Estado(models.TextChoices):
        ABIERTA = "ABI", "Abierta"
        COBRADA = "COB", "Cobrada"
        ANULADA = "ANU", "Anulada"

    class Tipo(models.TextChoices):
        MESA = "MES", "Mesa"
        LLEVAR = "LLE", "Para llevar"
        DELIVERY = "DEL", "Delivery"

    class Envio(models.TextChoices):
        PREPARANDO = "PRE", "Preparando"
        EN_CAMINO = "CAM", "En camino"
        ENTREGADO = "ENT", "Entregado"

    mesa = models.ForeignKey(Mesa, on_delete=models.PROTECT, null=True, blank=True, related_name="cuentas",
                             help_text="Vacío = para llevar / delivery.")
    nombre = models.CharField("cliente o referencia", max_length=60, blank=True, help_text='Para llevar: "Juan", "Delivery Av. Grau".')
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.MESA)
    # --- delivery ---
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.SET_NULL, null=True, blank=True, related_name="pedidos")
    telefono = models.CharField("celular", max_length=20, blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    referencia = models.CharField(max_length=200, blank=True, help_text='Ej.: "Frente al parque, puerta verde".')
    paga_con = models.CharField("paga con", max_length=40, blank=True, help_text='Ej.: "100", "Yape", "ya pagó".')
    costo_envio = models.DecimalField("costo de envío", max_digits=8, decimal_places=2, default=CERO)
    estado_envio = models.CharField(max_length=3, choices=Envio.choices, blank=True)
    repartidor = models.CharField(max_length=60, blank=True)
    salio_en = models.DateTimeField(null=True, blank=True)
    entregado_en = models.DateTimeField(null=True, blank=True)
    personas = models.PositiveSmallIntegerField(default=1)
    mozo = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cuentas_atendidas")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ABIERTA)
    pidio_cuenta = models.BooleanField(default=False)
    abierta_en = models.DateTimeField(default=timezone.now)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "cuenta"
        verbose_name_plural = "cuentas"
        ordering = ["-abierta_en"]
        constraints = [models.UniqueConstraint(fields=["mesa"], condition=Q(estado="ABI"), name="una_cuenta_abierta_por_mesa")]

    def __str__(self):
        return self.titulo

    @property
    def titulo(self):
        if self.mesa_id:
            return f"Mesa {self.nombres_mesas}"
        tipo = "Delivery" if self.es_delivery else "Para llevar"
        return f"{tipo} #{self.pk}" + (f" · {self.nombre}" if self.nombre else "")

    @property
    def unidas(self):
        """Mesas pegadas a esta cuenta (además de la principal)."""
        if not hasattr(self, "_unidas"):
            self._unidas = [m for m in self.mesas_unidas.all() if m.pk != self.mesa_id] if self.pk else []
        return self._unidas

    @property
    def nombres_mesas(self):
        return " + ".join([self.mesa.nombre] + [m.nombre for m in self.unidas]) if self.mesa_id else ""

    @property
    def es_delivery(self):
        return self.tipo == self.Tipo.DELIVERY

    @property
    def mapa_url(self):
        from urllib.parse import quote

        if not self.direccion:
            return ""
        from core.models import Ajustes

        a = Ajustes.cargar()
        return "https://www.google.com/maps/search/?api=1&query=" + quote(", ".join(x for x in [self.direccion, a.distrito] if x))

    @property
    def vuelto_para(self):
        """Si "paga con" es un monto, el vuelto que debe llevar el repartidor."""
        from decimal import InvalidOperation

        texto = self.paga_con.replace("S/", "").replace(",", ".").strip()
        try:
            monto = Decimal(texto)
        except (InvalidOperation, ValueError):
            return None
        falta = self.total_por_cobrar
        return monto - falta if monto.is_finite() and monto >= falta else None

    @property
    def abierta(self):
        return self.estado == self.Estado.ABIERTA

    @property
    def minutos(self):
        return int((timezone.now() - self.abierta_en).total_seconds() // 60)

    def items_vigentes(self):
        return self.items.filter(anulado=False)

    def por_cobrar(self):
        return self.items.filter(anulado=False, venta__isnull=True)

    def por_enviar(self):
        return self.items.filter(anulado=False, enviado_en__isnull=True)

    def pagada(self, items=None):
        """Abierta, sin nada por cobrar y con algo ya cobrado: pagaron, pero siguen en la mesa (o esperan comida)."""
        items = [i for i in (self.items.all() if items is None else items) if not i.anulado]
        return self.abierta and bool(items) and all(i.venta_id for i in items)

    @property
    def total_consumido(self):
        return sum((i.subtotal for i in self.items_vigentes()), CERO)

    @property
    def total_por_cobrar(self):
        return sum((i.subtotal for i in self.por_cobrar()), CERO)


class ItemCuenta(models.Model):
    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="items")
    variante = models.ForeignKey("productos.Variante", on_delete=models.PROTECT, related_name="+")
    descripcion = models.CharField(max_length=240)
    cantidad = models.DecimalField(max_digits=10, decimal_places=3)
    precio = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio al momento de pedirlo.")
    nota = models.CharField(max_length=120, blank=True, help_text='Ej.: "sin cebolla", "bien caliente".')
    opciones = models.JSONField(default=list, blank=True, help_text="Opciones elegidas (término, acompañamiento, adicionales).")
    agregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado = models.DateTimeField(default=timezone.now)
    area = models.CharField("se prepara en", max_length=3, default="COC", help_text="Copia de la categoría al pedir: COC cocina, BAR barra, MOZ lo sirve el mozo.")
    enviado_en = models.DateTimeField("enviado a cocina", null=True, blank=True)
    listo_en = models.DateTimeField("listo en cocina", null=True, blank=True)
    servido_en = models.DateTimeField(null=True, blank=True)
    cortesia = models.BooleanField("cortesía", default=False, help_text="No se cobra (va por la casa).")
    cortesia_motivo = models.CharField(max_length=120, blank=True)
    cortesia_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name="autorizó la cortesía")
    es_envio = models.BooleanField("costo de envío", default=False, help_text="La línea del delivery: no va a cocina.")
    anulado = models.BooleanField(default=False)
    motivo_anulacion = models.CharField(max_length=200, blank=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    venta = models.ForeignKey("ventas.Venta", on_delete=models.PROTECT, null=True, blank=True, related_name="items_cuenta")

    class Meta:
        verbose_name = "ítem de cuenta"
        verbose_name_plural = "ítems de cuenta"
        ordering = ["creado", "id"]

    def __str__(self):
        return f"{self.cantidad.normalize():f} × {self.descripcion}"

    @property
    def subtotal(self):
        """Lo que se cobra (0 si es cortesía)."""
        return Decimal("0.00") if self.cortesia else self.valor

    @property
    def valor(self):
        """Lo que valdría al precio de carta (para controlar las cortesías)."""
        return (self.precio * self.cantidad).quantize(Decimal("0.01"))

    @property
    def texto_opciones(self):
        return ", ".join(o["n"] for o in self.opciones or [] if not o.get("c"))

    @property
    def enviado(self):
        return self.enviado_en is not None
