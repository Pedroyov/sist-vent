from django.conf import settings
from django.db import models

from .utils import TamanoMaximo


class Rubro(models.TextChoices):
    """Tipo de negocio. Sirve para ajustar textos y opciones por defecto (mesas, tallas, servicios…)."""

    TIENDA = "TIE", "Tienda / bodega"
    RESTAURANTE = "RES", "Restaurante / cafetería"
    ROPA = "ROP", "Tienda de ropa y calzado"
    LIBRERIA = "LIB", "Librería / útiles escolares"
    PELUQUERIA = "PEL", "Peluquería / barbería / spa"
    OTRO = "OTR", "Otro"


class Ajustes(models.Model):
    """Ajustes generales del sistema y datos del negocio (una sola fila)."""

    modulos_inactivos = models.JSONField("módulos desactivados", default=list, blank=True)

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
        from .utils import numero_whatsapp

        d = numero_whatsapp(self.whatsapp)
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

        carpeta = os.path.join(settings.MEDIA_ROOT, "negocio")
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
