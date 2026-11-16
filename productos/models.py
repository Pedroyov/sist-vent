from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.utils import TamanoMaximo

CERO = Decimal("0")


class Area(models.TextChoices):
    """Dónde se prepara lo que se pide en mesas."""
    COCINA = "COC", "Cocina"
    BARRA = "BAR", "Barra"
    MOZO = "MOZ", "Lo sirve el mozo"


def area_sugerida(nombre):
    """Para categorías nuevas: gaseosas y cervezas las saca el mozo; tragos y jugos, la barra."""
    n = nombre.lower()
    if any(p in n for p in ("trago", "cóctel", "coctel", "jugo", "batido", "barra", "café", "cafe", "infusi", "caliente")):
        return Area.BARRA
    if any(p in n for p in ("bebida", "gaseosa", "cerveza", "agua", "vino", "licor")):
        return Area.MOZO
    return Area.COCINA


class Categoria(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    area = models.CharField("se prepara en", max_length=3, choices=Area.choices, default=Area.COCINA,
                            help_text="Al enviar un pedido de mesa: a la cocina, a la barra, o lo lleva el mozo directamente (gaseosas, agua).")
    orden = models.PositiveSmallIntegerField(default=0, help_text="Las de número menor salen primero.")
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


def agotado_hoy(fecha):
    """Lo agotado vale solo por el día: al día siguiente vuelve a estar disponible sin hacer nada."""
    return bool(fecha) and timezone.localtime(fecha).date() == timezone.localdate()


class GrupoOpciones(models.Model):
    """Opciones que se eligen al pedir un producto: término de la carne, acompañamiento, adicionales con precio…
    Un grupo se puede usar en varios productos."""

    nombre = models.CharField(max_length=60, unique=True, help_text='Ej.: "Término de la carne", "Adicionales".')
    minimo = models.PositiveSmallIntegerField("mínimo a elegir", default=0,
                                              help_text="0 = opcional. 1 = hay que elegir sí o sí (ej.: el término).")
    maximo = models.PositiveSmallIntegerField("máximo a elegir", default=1, help_text="0 = sin límite (ej.: adicionales).")
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)
    diario = models.BooleanField("cambia cada día", default=False,
                                 help_text="Para el menú del día (entradas, segundos): sus opciones se arman cada mañana en «Menú del día».")

    class Meta:
        verbose_name = "grupo de opciones"
        verbose_name_plural = "grupos de opciones"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    @property
    def regla(self):
        if self.minimo and self.minimo == self.maximo:
            return f"Elegir {self.minimo}"
        if self.minimo:
            return f"Elegir de {self.minimo} a {self.maximo}" if self.maximo else f"Elegir al menos {self.minimo}"
        if self.maximo == 1:
            return "Opcional, uno"
        return f"Opcional, hasta {self.maximo}" if self.maximo else "Opcional, varios"


class Opcion(models.Model):
    grupo = models.ForeignKey(GrupoOpciones, on_delete=models.CASCADE, related_name="opciones")
    nombre = models.CharField(max_length=60)
    precio = models.DecimalField("precio adicional", max_digits=8, decimal_places=2, default=Decimal("0"),
                                 validators=[MinValueValidator(Decimal("0"))])
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)
    agotada_en = models.DateTimeField(null=True, blank=True)
    por_defecto = models.BooleanField("viene incluida", default=False,
                                      help_text="Ya aparece elegida al pedir (ej.: las alitas vienen con papas); se puede cambiar.")

    class Meta:
        verbose_name = "opción"
        verbose_name_plural = "opciones"
        ordering = ["grupo", "orden", "id"]
        constraints = [models.UniqueConstraint(fields=["grupo", "nombre"], name="opcion_unica_por_grupo")]

    def __str__(self):
        return self.nombre

    @property
    def agotada(self):
        return agotado_hoy(self.agotada_en)


class Unidad(models.TextChoices):
    UNIDAD = "UND", "Unidad"
    KILO = "KG", "Kilo"
    LITRO = "LT", "Litro"
    METRO = "MT", "Metro"
    PAQUETE = "PAQ", "Paquete"
    CAJA = "CAJ", "Caja"
    DOCENA = "DOC", "Docena"
    PAR = "PAR", "Par"
    SERVICIO = "SRV", "Servicio"


# Unidades que se venden con decimales (1.5 kg, 0.75 m)
FRACCIONABLES = {Unidad.KILO, Unidad.LITRO, Unidad.METRO}


class Producto(models.Model):
    class Tipo(models.TextChoices):
        PRODUCTO = "P", "Producto"
        SERVICIO = "S", "Servicio"

    tipo = models.CharField(max_length=1, choices=Tipo.choices, default=Tipo.PRODUCTO,
                            help_text="Un servicio (corte, manicure, delivery…) no maneja stock.")
    nombre = models.CharField(max_length=150)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="productos", verbose_name="categoría")
    descripcion = models.TextField("descripción", blank=True)
    unidad = models.CharField(max_length=3, choices=Unidad.choices, default=Unidad.UNIDAD)
    precio = models.DecimalField("precio de venta", max_digits=10, decimal_places=2,
                                 validators=[MinValueValidator(CERO)])
    costo = models.DecimalField("costo", max_digits=10, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(CERO)], help_text="Lo que te cuesta. Opcional; sirve para ver la ganancia.")
    maneja_stock = models.BooleanField("controlar stock", default=True,
                                       help_text="Desmárcalo para lo que no se cuenta (platos preparados, servicios).")
    stock_minimo = models.DecimalField("stock mínimo", max_digits=12, decimal_places=3, default=CERO,
                                       validators=[MinValueValidator(CERO)],
                                       help_text="Cuando quede esta cantidad o menos, avisa que hay que reponer. Con variantes, vale para cada una.")
    duracion_min = models.PositiveSmallIntegerField("duración (minutos)", null=True, blank=True,
                                                    help_text="Para servicios. Sirve más adelante para las citas.")
    imagen = models.ImageField(upload_to="productos/", blank=True, validators=[TamanoMaximo(5)])
    area = models.CharField("se prepara en", max_length=3, choices=Area.choices, blank=True,
                            help_text="Vacío = como su categoría. Cámbialo solo si este producto va a otro lado.")
    grupos = models.ManyToManyField(GrupoOpciones, blank=True, related_name="productos", verbose_name="opciones al pedir",
                                    help_text="Término, acompañamiento, adicionales… Se crean en Productos → Opciones.")
    agotado_en = models.DateTimeField(null=True, blank=True, help_text="Agotado por hoy (vuelve solo mañana).")
    activo = models.BooleanField(default=True, help_text="Desmárcalo para dejar de venderlo sin borrarlo.")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if self.tipo == self.Tipo.SERVICIO:
            self.maneja_stock = False
            self.unidad = Unidad.SERVICIO
        elif self.unidad == Unidad.SERVICIO:
            self.unidad = Unidad.UNIDAD
        super().save(*args, **kwargs)

    @property
    def area_efectiva(self):
        return self.area or (self.categoria.area if self.categoria_id else Area.COCINA)

    @property
    def agotado(self):
        return agotado_hoy(self.agotado_en)

    @property
    def es_servicio(self):
        return self.tipo == self.Tipo.SERVICIO

    @property
    def fraccionable(self):
        return self.unidad in FRACCIONABLES

    def variantes_activas(self):
        return self.variantes.filter(activa=True)

    @property
    def tiene_variantes(self):
        return self.variantes.filter(activa=True).exclude(nombre="").exists()

    def variante_unica(self):
        """La variante sin nombre de un producto que no tiene tallas, colores, etc."""
        return self.variantes.filter(nombre="").first()

    @property
    def stock_total(self):
        return self.variantes.filter(activa=True).aggregate(t=models.Sum("stock"))["t"] or CERO

    @property
    def margen(self):
        """% de ganancia sobre el precio de venta."""
        if self.costo is None or not self.precio:
            return None
        return (self.precio - self.costo) / self.precio * 100

    def procesar_imagen(self):
        """Reduce la imagen subida a 800 px como máximo (las fotos del celular pesan mucho)."""
        from PIL import Image, ImageOps

        with Image.open(self.imagen.path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            im.thumbnail((800, 800))
            fmt = "PNG" if self.imagen.path.lower().endswith(".png") else "JPEG"
            if fmt == "JPEG" and im.mode == "RGBA":
                im = im.convert("RGB")
            im.save(self.imagen.path, fmt, quality=85, optimize=True)


class Componente(models.Model):
    """Lo que lleva un plato (pollo, papas, ensalada…). Al pedir se puede quitar ("SIN ENSALADA") o cambiar por otra
    opción de un grupo (papas -> arroz). Más adelante, con recetas, cada componente tendrá su insumo y su cantidad."""

    producto = models.ForeignKey("Producto", on_delete=models.CASCADE, related_name="componentes")
    nombre = models.CharField(max_length=60)
    quitable = models.BooleanField("se puede quitar", default=True)
    cambiar_con = models.ForeignKey(GrupoOpciones, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                    verbose_name="se puede cambiar por",
                                    help_text="Grupo con las alternativas (ej.: Acompañamiento: papas, arroz, ensalada).")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "componente"
        verbose_name_plural = "componentes (qué lleva)"
        ordering = ["producto", "orden", "id"]

    def __str__(self):
        return self.nombre


class Variante(models.Model):
    """Lo que realmente se vende y se cuenta. Un producto sin tallas ni colores tiene una sola variante sin nombre."""

    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="variantes")
    nombre = models.CharField(max_length=80, blank=True, help_text='Ej.: "M / Rojo", "Familiar", "1 L".')
    codigo = models.CharField("código", max_length=50, blank=True,
                              help_text="Código de barras o código interno. Opcional, pero no se puede repetir.")
    precio = models.DecimalField("precio", max_digits=10, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(CERO)], help_text="Vacío = el precio del producto.")
    costo = models.DecimalField("costo", max_digits=10, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(CERO)], help_text="Vacío = el costo del producto.")
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=CERO, editable=False)
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "variante"
        verbose_name_plural = "variantes"
        ordering = ["producto", "orden", "id"]
        constraints = [
            models.UniqueConstraint(fields=["producto", "nombre"], name="variante_unica_por_producto"),
            models.UniqueConstraint(fields=["codigo"], condition=~Q(codigo=""), name="codigo_variante_unico"),
        ]

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        return f"{self.producto.nombre} · {self.nombre}" if self.nombre else self.producto.nombre

    @property
    def precio_venta(self):
        return self.precio if self.precio is not None else self.producto.precio

    @property
    def costo_efectivo(self):
        return self.costo if self.costo is not None else self.producto.costo

    @property
    def por_reponer(self):
        return self.producto.maneja_stock and self.stock <= self.producto.stock_minimo


class MovimientoStock(models.Model):
    """Kardex: cada entrada o salida de mercadería, con el saldo que quedó."""

    class Tipo(models.TextChoices):
        INICIAL = "INI", "Stock inicial"
        INGRESO = "ING", "Ingreso (compra)"
        SALIDA = "SAL", "Salida (merma, uso interno)"
        AJUSTE = "AJU", "Ajuste por conteo"
        VENTA = "VEN", "Venta"
        DEVOLUCION = "DEV", "Devolución"

    variante = models.ForeignKey(Variante, on_delete=models.PROTECT, related_name="movimientos")
    fecha = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, help_text="Positiva entra, negativa sale.")
    saldo = models.DecimalField(max_digits=12, decimal_places=3)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    referencia = models.CharField(max_length=60, blank=True, help_text='Ej.: "Venta 000123", "Factura F001-45".')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+")

    class Meta:
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["fecha"])]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad} · {self.variante}"

    @property
    def entra(self):
        return self.cantidad > 0
