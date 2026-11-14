"""Datos de ejemplo para probar el sistema: python manage.py datos_demo

Crea los datos del negocio y usuarios de prueba (clave demo1234). Cada app nueva
puede agregar aquí sus propios datos de ejemplo (productos, ventas, clientes…).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Ajustes, Rubro
from core.permisos import ADMINISTRACION, CAJERO, VENDEDOR

CLAVE = "demo1234"
USUARIOS = [
    # (usuario, nombres, apellidos, rol, superusuario)
    ("admin", "Administrador", "Principal", None, True),
    ("gerente", "Rosa", "Quispe Huamán", ADMINISTRACION, False),
    ("cajero", "Luis", "Ramos Torres", CAJERO, False),
    ("vendedor", "Ana", "Flores Díaz", VENDEDOR, False),
]


class Command(BaseCommand):
    help = "Carga datos de ejemplo (negocio y usuarios de prueba con clave demo1234)."

    @transaction.atomic
    def handle(self, *args, **opciones):
        a = Ajustes.cargar()
        a.rubro = Rubro.TIENDA
        a.nombre = a.nombre or "Bazar Demo"
        a.nombre_corto = a.nombre_corto or "Bazar Demo"
        a.lema = a.lema or "Todo lo que necesitas, cerca de ti"
        a.ruc = a.ruc or "20123456789"
        a.direccion = a.direccion or "Av. Principal 123"
        a.distrito = a.distrito or "Lima"
        a.whatsapp = a.whatsapp or "987654321"
        a.nota_ticket = a.nota_ticket or "Gracias por su compra."
        a.save()

        User = get_user_model()
        for usuario, nombres, apellidos, rol, superusuario in USUARIOS:
            u, _ = User.objects.get_or_create(username=usuario)
            u.first_name, u.last_name = nombres, apellidos
            u.is_superuser = u.is_staff = superusuario
            u.is_active = True
            u.set_password(CLAVE)
            u.save()
            if rol:
                u.groups.add(Group.objects.get(name=rol))
        self.stdout.write(self.style.SUCCESS(
            f"Datos de ejemplo listos. Usuarios: {', '.join(x[0] for x in USUARIOS)} (clave {CLAVE})."))
