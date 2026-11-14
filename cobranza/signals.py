"""Cuando se matricula o retira a un alumno, sus deudas se crean o anulan solas."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from alumnos.models import Matricula

from . import servicios
from .models import Descuento


@receiver(post_save, sender=Matricula)
def matricula_guardada(sender, instance, **kwargs):
    servicios.asignar_cargos(instance)
    servicios.actualizar_por_estado(instance)


@receiver(post_save, sender=Descuento)
@receiver(post_delete, sender=Descuento)
def descuento_cambiado(sender, instance, **kwargs):
    servicios.recalcular_descuentos(instance.alumno_id, instance.anio_lectivo)
