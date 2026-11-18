"""Personal: quienes trabajan en el negocio (estilistas, mozos, vendedores, repartidores…).

Es parte de la base del sistema: cualquier módulo lo usa (Citas para la agenda, Delivery para los repartidores, Vender
para «Atendió», Reportes para el desempeño y las comisiones). Una persona puede tener usuario o no (un repartidor o un
ayudante que no entra al sistema). Lo propio de cada módulo cuelga de aquí: los horarios y días libres son de Citas.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

COLORES = [("#0d6efd", "Azul"), ("#d63384", "Rosado"), ("#198754", "Verde"), ("#fd7e14", "Naranja"), ("#6f42c1", "Morado"),
           ("#20c997", "Turquesa"), ("#dc3545", "Rojo"), ("#795548", "Marrón")]


class Persona(models.Model):
    nombre = models.CharField(max_length=60, help_text="Como lo conocen los clientes: «Carla», «Don Luis».")
    telefono = models.CharField("celular", max_length=20, blank=True)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="persona",
                                   help_text="Opcional: si entra al sistema con su propio usuario.")
    color = models.CharField(max_length=7, choices=COLORES, default=COLORES[0][0])
    comision = models.DecimalField("comisión (%)", max_digits=5, decimal_places=2, default=Decimal("0"),
                                   validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
                                   help_text="Porcentaje de lo que atiende que se le paga (solo si el negocio paga comisiones).")
    # Qué hace (cada módulo muestra solo lo suyo)
    atiende_citas = models.BooleanField("atiende citas", default=True, help_text="Sale en la agenda de citas (estilista, barbero, terapeuta).")
    reparte = models.BooleanField("reparte delivery", default=False, help_text="Sale en la lista de repartidores.")
    servicios = models.ManyToManyField("productos.Producto", blank=True, related_name="personal",
                                       help_text="Los servicios que sabe hacer (para las citas). Ninguno marcado = hace todos.")
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "persona"
        verbose_name_plural = "personal"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def hace(self, producto_id):
        ids = getattr(self, "_servicios_ids", None)
        if ids is None:
            ids = self._servicios_ids = set(self.servicios.values_list("pk", flat=True))
        return not ids or producto_id is None or producto_id in ids


def de_usuario(user):
    """La persona de un usuario (o None)."""
    if not getattr(user, "is_authenticated", False):
        return None
    return Persona.objects.filter(usuario=user).first()


def nombre_de(user):
    """Cómo se muestra a un usuario en los reportes: el nombre de su persona, o su nombre de usuario."""
    p = getattr(user, "persona", None) if user is not None else None
    if p is not None:
        return p.nombre
    return (user.get_full_name() or user.username) if user is not None else ""
