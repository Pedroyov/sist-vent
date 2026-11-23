from decimal import Decimal

from django.conf import settings
from django.db import models

from .cifrado import CampoCifrado

from .utils import TamanoMaximo


class Rubro(models.TextChoices):
    """Tipo de negocio. Sirve para ajustar textos y opciones por defecto (mesas, tallas, servicios…)."""

    TIENDA = "TIE", "Tienda / bodega"
    RESTAURANTE = "RES", "Restaurante / cafetería"
    ROPA = "ROP", "Tienda de ropa y calzado"
    LIBRERIA = "LIB", "Librería / útiles escolares"
    PELUQUERIA = "PEL", "Peluquería / barbería / spa"
    ACADEMIA = "ACA", "Academia / gimnasio / taller"
    OTRO = "OTR", "Otro"


def modulos_inactivos_iniciales():
    """Lo de restaurante empieza apagado (Mesas se activa al elegir ese rubro)."""
    return ["mesas", "cocina", "delivery", "facturacion", "cobranzas", "reservas", "citas", "compras"]


def funciones_inactivas_iniciales():
    """Una instalación nueva empieza como tienda: solo variantes (ver core/rubros.py)."""
    return ["combos", "servicios", "agotados", "atendio", "comisiones", "pagos", "precios", "promociones", "monedero"]


class Ajustes(models.Model):
    """Ajustes generales del sistema y datos del negocio (una sola fila)."""

    modulos_inactivos = models.JSONField("módulos desactivados", default=modulos_inactivos_iniciales, blank=True)
    funciones_inactivas = models.JSONField("funciones avanzadas ocultas", default=funciones_inactivas_iniciales, blank=True)

    # --- Datos del negocio (Configuración → Datos del negocio) ---
    rubro = models.CharField("rubro", max_length=3, choices=Rubro.choices, default=Rubro.TIENDA)
    nombre = models.CharField("nombre comercial", max_length=150, blank=True,
                              help_text='Como aparece en tickets y comprobantes. Ej.: "Bazar Santa Rosa".')
    nombre_corto = models.CharField("nombre corto", max_length=30, blank=True,
                                    help_text="Para el menú y el ícono del celular. Ej.: «Santa Rosa».")
    lema = models.CharField("eslogan", max_length=150, blank=True)
    logo = models.ImageField("logo", upload_to="negocio/", blank=True, validators=[TamanoMaximo(5)],
                             help_text="PNG o JPG, de preferencia cuadrado y con fondo blanco o transparente.")
    razon_social = models.CharField("razón social", max_length=150, blank=True)
    ruc = models.CharField("RUC", max_length=11, blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    distrito = models.CharField("distrito / ciudad", max_length=100, blank=True)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp del negocio", max_length=20, blank=True,
                                help_text="Se muestra en tickets y mensajes para que los clientes respondan.")
    email = models.EmailField("correo", blank=True)
    web = models.URLField("página web o redes", blank=True)
    nota_ticket = models.CharField("nota al pie del ticket", max_length=250, blank=True,
                                   help_text='Ej.: "Gracias por su compra. No se aceptan devoluciones después de 7 días."')
    # --- Opciones de venta ---
    vender_sin_caja = models.BooleanField(
        "permitir vender sin caja abierta", default=False,
        help_text="Si está desmarcado (recomendado), cada venta queda en la caja abierta de quien cobra y así cuadra al cierre.")
    cierre_ciego = models.BooleanField(
        "cierre ciego para cajeros", default=True,
        help_text="El cajero cuenta sin ver cuánto debería haber y el sistema calcula la diferencia al cerrar (recomendado con empleados). "
                  "Desmárcalo si quien cobra es de total confianza: verá «Faltan S/ …» mientras cuenta. Administración siempre lo ve.")
    propina_activa = models.BooleanField(
        "pedir propina al cobrar", default=False, help_text="Muestra un campo de propina al cobrar (útil en restaurantes).")
    metodos_pago = models.JSONField("métodos de pago que acepta", default=list, blank=True,
                                    help_text="Vacío = todos. El efectivo siempre está.")
    monedero_porcentaje = models.DecimalField(
        "% de monedero", max_digits=4, decimal_places=2, default=Decimal("2"),
        help_text="De cada compra pagada por un cliente registrado, este % vuelve como saldo a favor (función Monedero).")
    monedero_dias = models.PositiveSmallIntegerField("el monedero vence a los (días)", default=90)
    dias_fiado = models.PositiveSmallIntegerField(
        "días para pagar el fiado", default=15,
        help_text="Cada fiado vence a los días indicados; con algo vencido no se le vuelve a fiar sin el permiso de pasar el límite. "
                  "0 = el fiado no vence. A cada cliente se le puede dar otro plazo.")
    dias_devolucion = models.PositiveSmallIntegerField(
        "días para devolver", default=30, help_text="Hasta cuántos días después de la venta se aceptan devoluciones de productos.")
    exigir_operacion = models.BooleanField(
        "pedir el N° de operación en Yape y Plin", default=False,
        help_text="Al cobrar con Yape o Plin no se confirma sin el número de operación. Ayuda a conciliar y a detectar capturas falsas; en hora punta frena un poco la caja.")
    descuentos_activos = models.BooleanField("permitir descuentos al cobrar", default=True,
                                             help_text="Si lo desmarcas, nadie ve el campo de descuento.")
    cortesias_activas = models.BooleanField("permitir cortesías en mesas", default=True,
                                            help_text="Platos «por la casa» (S/ 0.00), con motivo y autorización.")
    # --- Impresión y cocina ---
    ticket_ancho = models.PositiveSmallIntegerField(
        "papel de la ticketera", choices=[
            (80, "80 mm (el más común)"),
            (76, "76 mm (de impacto o matricial, como las de cocina)"),
            (58, "58 mm (pequeñas o portátiles; también las de 57 mm)"),
            (210, "Hoja A4 o carta (impresora normal)")],
        default=80, help_text="El ancho del rollo de papel. Si no lo sabes, mídelo con una regla: 8 cm, 7.6 cm o 5.8 cm.")
    imprimir_auto = models.BooleanField(
        "imprimir el ticket al terminar cada venta", default=False,
        help_text="Abre la impresión sola. Con Chrome en modo «kiosk-printing» imprime sin preguntar.")
    delivery_costo = models.DecimalField("costo de envío habitual", max_digits=8, decimal_places=2, default=Decimal("0"),
                                         help_text="Se propone en cada delivery; se puede cambiar en cada pedido.")
    nivel_pedido = models.PositiveSmallIntegerField(
        "cómo se toman los pedidos", default=1,
        choices=[(1, "Simple: el producto y una nota escrita (ej.: «sin cebolla»)"),
                 (2, "Con opciones: término, acompañamiento, cremas, adicionales con precio y menú del día"),
                 (3, "Detallado: además, qué lleva cada plato para quitar o cambiar cosas")],
        help_text="Lo que no uses no aparece ni se configura. Puedes cambiarlo cuando quieras.")
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

    @property
    def metodos_aceptados(self):
        """Códigos de los métodos de pago activos, en el orden de siempre (efectivo primero, siempre está)."""
        from ventas.models import MetodoPago

        elegidos = set(self.metodos_pago or MetodoPago.values) | {MetodoPago.EFECTIVO}
        return [m for m in MetodoPago.values if m in elegidos]

    # --- módulos que antes eran ajustes: se leen igual (NEGOCIO.cocina_pantalla, NEGOCIO.delivery_activo) ---
    def tiene_modulo(self, codigo):
        from .permisos import modulos_activos

        return codigo in modulos_activos(self)

    @property
    def cocina_pantalla(self):
        return self.tiene_modulo("cocina")

    @property
    def delivery_activo(self):
        return self.tiene_modulo("delivery")

    # --- funciones avanzadas (core/rubros.py): ocultas si el negocio no las usa ---
    def usa(self, funcion):
        return funcion not in (self.funciones_inactivas or [])

    @property
    def papel(self):
        """Cómo se arma la hoja de lo impreso: ancho útil, tamaño de letra y si es una hoja normal (A4) en vez de un rollo."""
        ancho, letra = {58: ("48mm", "10.5px"), 76: ("64mm", "11.5px"), 210: ("120mm", "13px")}.get(self.ticket_ancho, ("72mm", "12px"))
        return {"ancho": ancho, "letra": letra, "hoja": self.ticket_ancho == 210, "rollo": self.ticket_ancho if self.ticket_ancho != 210 else 0}

    @property
    def usa_comisiones(self):
        return self.usa("comisiones")

    @property
    def usa_atendio(self):
        return self.usa("atendio")

    @property
    def usa_precios(self):
        return self.usa("precios")

    @property
    def usa_promociones(self):
        return self.usa("promociones")

    @property
    def usa_monedero(self):
        return self.usa("monedero")

    @property
    def usa_pagos(self):
        return self.usa("pagos")

    @property
    def usa_variantes(self):
        return self.usa("variantes")

    @property
    def usa_combos(self):
        return self.usa("combos")

    @property
    def usa_servicios(self):
        return self.usa("servicios")

    @property
    def usa_agotados(self):
        return self.usa("agotados")

    @property
    def usa_opciones(self):
        return self.nivel_pedido >= 2

    @property
    def usa_lleva(self):
        return self.nivel_pedido >= 3

    # --- valores a mostrar (con respaldo en el .env si aún no se llenan) ---
    @property
    def nombre_mostrar(self):
        return self.nombre or settings.NEGOCIO_NOMBRE

    @property
    def corto_mostrar(self):
        return self.nombre_corto or settings.NEGOCIO_NOMBRE_CORTO

    def icono_url(self, tam=192):
        """Ícono cuadrado generado del logo; si no hay logo, el ícono del sistema."""
        from django.templatetags.static import static

        if self.logo and self.version_logo:
            return f"{settings.MEDIA_URL}negocio/icono-{tam}.png?v={self.version_logo}"
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
            return f"{settings.MEDIA_URL}negocio/logo.png?v={self.version_logo}"
        return self.icono_url(192)

    @property
    def tiene_logo(self):
        return bool(self.logo and self.version_logo)

    @property
    def whatsapp_link(self):
        from .utils import enlace_whatsapp

        return enlace_whatsapp(self.whatsapp)

    def linea_contacto(self):
        partes = [x for x in (self.direccion, self.distrito) if x]
        tel = " / ".join(x for x in (self.telefono, self.whatsapp) if x)
        if tel:
            partes.append(f"Telf. {tel}")
        return " · ".join(partes)

    def generar_iconos(self):
        """Del logo subido saca: logo.png (máx. 600 px) e íconos cuadrados 180/192/512 para el celular."""
        from PIL import Image, ImageOps

        from .utils import guardar_archivo, imagen_a_bytes

        with self.logo.open("rb") as archivo, Image.open(archivo) as im:  # en disco o en Spaces
            im = ImageOps.exif_transpose(im).convert("RGBA")
            # recorta bordes vacíos (transparentes o blancos)
            fondo = Image.new("RGBA", im.size, (255, 255, 255, 0))
            caja = Image.alpha_composite(fondo, im).getbbox()
            if caja:
                im = im.crop(caja)
            logo = im.copy()
            logo.thumbnail((600, 600))
            guardar_archivo("negocio/logo.png", imagen_a_bytes(logo, "PNG"))
            for tam in (180, 192, 512):
                lienzo = Image.new("RGBA", (tam, tam), (255, 255, 255, 255))
                interior = int(tam * 0.84)
                copia = im.copy()
                copia.thumbnail((interior, interior), Image.LANCZOS)
                lienzo.alpha_composite(copia, ((tam - copia.width) // 2, (tam - copia.height) // 2))
                guardar_archivo(f"negocio/icono-{tam}.png", imagen_a_bytes(lienzo.convert("RGB"), "PNG"))
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


class Bitacora(models.Model):
    """Registro de acciones críticas (anulaciones, precios, permisos, caja…). Solo se agrega: no se edita ni se borra.
    Cada fila guarda su huella (SHA-256) que incluye la huella de la anterior: si alguien toca la tabla por fuera del
    sistema, la cadena se rompe y `core.bitacora.verificar()` dice desde qué fila. En PostgreSQL, además, un disparador
    rechaza UPDATE y DELETE. Se escribe solo con `core.bitacora.anotar`."""

    n = models.PositiveIntegerField("N°", unique=True)
    fecha = models.DateTimeField(db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
                                related_name="+")
    usuario_nombre = models.CharField(max_length=150, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    accion = models.CharField(max_length=40, db_index=True)
    descripcion = models.CharField(max_length=300)
    objeto_tipo = models.CharField(max_length=40, blank=True)
    objeto_id = models.CharField(max_length=20, blank=True)
    antes = models.JSONField(null=True, blank=True)
    despues = models.JSONField(null=True, blank=True)
    huella_anterior = models.CharField(max_length=64, blank=True)
    huella = models.CharField(max_length=64)

    class Meta:
        verbose_name = "entrada de bitácora"
        verbose_name_plural = "bitácora"
        ordering = ["-n"]
        indexes = [models.Index(fields=["objeto_tipo", "objeto_id"])]

    def __str__(self):
        return f"{self.n} · {self.accion} · {self.descripcion}"

    def calcular_huella(self):
        import hashlib
        import json

        datos = [self.n, self.fecha.isoformat(), self.usuario_id, self.usuario_nombre, self.ip, self.accion, self.descripcion,
                 self.objeto_tipo, self.objeto_id, self.antes, self.despues, self.huella_anterior]
        return hashlib.sha256(json.dumps(datos, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("La bitácora no se modifica.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("La bitácora no se borra.")


class SegundoFactor(models.Model):
    """Código de 6 dígitos de una app del celular (Google Authenticator o similar), además de la contraseña.
    La lógica está en core/dos_factor.py."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="segundo_factor")
    secreto = CampoCifrado()  # se guarda cifrado (core/cifrado.py)
    activo = models.BooleanField(default=False)
    activado_en = models.DateTimeField(null=True, blank=True)
    ultimo_paso = models.BigIntegerField(default=0, help_text="Último código usado: no se acepta dos veces.")
    respaldos = models.JSONField(default=list, blank=True, help_text="Huellas de los códigos de respaldo que quedan.")
    version = models.PositiveIntegerField(default=1, help_text="Al cambiar, los dispositivos recordados vuelven a pedir el código.")

    class Meta:
        verbose_name = "código del celular"
        verbose_name_plural = "códigos del celular"

    def __str__(self):
        return f"{self.usuario} ({'activo' if self.activo else 'sin activar'})"
