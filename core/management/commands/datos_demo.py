"""Datos de ejemplo para probar el sistema:

    python manage.py datos_demo                # bodega / tienda
    python manage.py datos_demo --rubro ROP    # TIE, RES, ROP, LIB, PEL

Crea los datos del negocio, usuarios de prueba (clave demo1234) y un catálogo de
ejemplo según el rubro. Cada app nueva agrega aquí sus propios datos de ejemplo.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Ajustes, Rubro
from core.permisos import ADMINISTRACION, CAJERO, COCINA, VENDEDOR

CLAVE = "demo1234"
USUARIOS = [
    # (usuario, nombres, apellidos, rol, superusuario)
    ("admin", "Administrador", "Principal", None, True),
    ("gerente", "Rosa", "Quispe Huamán", ADMINISTRACION, False),
    ("cajero", "Luis", "Ramos Torres", CAJERO, False),
    ("vendedor", "Ana", "Flores Díaz", VENDEDOR, False),
    ("cocina", "Pedro", "Huamán Ríos", COCINA, False),
]


class Command(BaseCommand):
    help = "Carga datos de ejemplo (negocio, usuarios de prueba con clave demo1234 y catálogo según el rubro)."

    def add_arguments(self, parser):
        parser.add_argument("--rubro", default=Rubro.TIENDA, choices=Rubro.values,
                            help="TIE tienda, RES restaurante, ROP ropa, LIB librería, PEL peluquería")

    @transaction.atomic
    def handle(self, *args, **opciones):
        from productos.demo import NEGOCIOS, cargar_catalogo

        rubro = opciones["rubro"]
        nombre, lema = NEGOCIOS.get(rubro, ("Negocio Demo", ""))
        a = Ajustes.cargar()
        a.rubro = rubro
        a.nombre = nombre
        a.nombre_corto = nombre
        a.lema = lema
        inactivos = [m for m in (a.modulos_inactivos or []) if m != "mesas"]
        a.modulos_inactivos = inactivos if rubro == Rubro.RESTAURANTE else inactivos + ["mesas"]
        a.cocina_pantalla = rubro == Rubro.RESTAURANTE
        a.propina_activa = rubro == Rubro.RESTAURANTE
        a.nivel_pedido = 3 if rubro == Rubro.RESTAURANTE else 2
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
        n = cargar_catalogo(rubro, User.objects.get(username="admin"))
        from ventas.demo import cargar_ventas
        from ventas.models import Venta

        # en restaurante casi todo pasa por las mesas: en el mostrador, pocas ventas por día
        nv = cargar_ventas(dias=14, por_dia=(3, 7)) if rubro == Rubro.RESTAURANTE else cargar_ventas()
        from clientes.demo import cargar_clientes

        cargar_clientes()
        if rubro == Rubro.RESTAURANTE:
            from mesas.demo import cargar_mesas

            cargar_mesas()
            from productos.demo import marcar_agotados_demo

            marcar_agotados_demo()
            nv = Venta.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Datos de ejemplo listos ({a.get_rubro_display()}, {n} productos, {nv} ventas). Usuarios: {', '.join(x[0] for x in USUARIOS)}"
            f"{', mozo' if rubro == Rubro.RESTAURANTE else ''} (clave {CLAVE})."))
