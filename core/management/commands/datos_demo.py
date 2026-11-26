"""Datos de ejemplo para probar el sistema:

    python manage.py datos_demo                # bodega / tienda
    python manage.py datos_demo --rubro ROP    # TIE, RES, ROP, LIB, PEL, ACA

Crea los datos del negocio, usuarios de prueba (clave demo1234) y un catálogo de
ejemplo según el rubro. Cada app nueva agrega aquí sus propios datos de ejemplo.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Ajustes, Rubro
from core.permisos import ADMINISTRACION, CAJERO, COCINA, MOZO, VENDEDOR

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
                            help="TIE tienda, RES restaurante, ROP ropa, LIB librería, PEL peluquería, ACA academia o gimnasio")

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
        restaurante = ("mesas", "cocina", "delivery", "reservas")
        inactivos = [m for m in (a.modulos_inactivos or []) if m not in restaurante]
        a.modulos_inactivos = inactivos if rubro == Rubro.RESTAURANTE else inactivos + list(restaurante)
        if rubro == Rubro.TIENDA:  # la bodega muestra el delivery sin mesas
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m != "delivery"]
        a.modulos_inactivos = [m for m in a.modulos_inactivos if m != "facturacion"]  # la demo la trae en modo prueba
        if rubro == Rubro.ACADEMIA:
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m not in ("cobranzas", "clientes")]
        elif "cobranzas" not in a.modulos_inactivos:
            a.modulos_inactivos.append("cobranzas")
        if rubro == Rubro.PELUQUERIA:
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m != "citas"]
        elif "citas" not in a.modulos_inactivos:
            a.modulos_inactivos.append("citas")
        if rubro in (Rubro.TIENDA, Rubro.ROPA, Rubro.LIBRERIA, Rubro.RESTAURANTE):  # quien compra mercadería o insumos registra sus compras
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m != "compras"]
        elif "compras" not in a.modulos_inactivos:
            a.modulos_inactivos.append("compras")
        a.razon_social = a.razon_social or f"{nombre.upper()} S.A.C."
        a.propina_activa = rubro == Rubro.RESTAURANTE
        a.nivel_pedido = 3 if rubro == Rubro.RESTAURANTE else 2
        if rubro == Rubro.RESTAURANTE and not a.delivery_costo:
            from decimal import Decimal

            a.delivery_costo = Decimal("5")
        a.ruc = a.ruc or "20123456789"
        a.direccion = a.direccion or "Av. Principal 123"
        a.distrito = a.distrito or "Lima"
        a.whatsapp = a.whatsapp or "987654321"
        a.nota_ticket = a.nota_ticket or "Gracias por su compra."
        a.funciones_inactivas = []  # se ajustan al rubro cuando el catálogo ya está cargado
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
                if rol == VENDEDOR and rubro == Rubro.RESTAURANTE:  # en restaurante, el vendedor es mozo
                    rol = MOZO
                u.groups.add(Group.objects.get(name=rol))
        n = cargar_catalogo(rubro, User.objects.get(username="admin"))
        from core.rubros import aplicar

        aplicar(a)  # funciones del rubro; las que el catálogo de ejemplo usa quedan a la vista
        if rubro == Rubro.RESTAURANTE:
            a.nivel_pedido = 3
            a.save(update_fields=["nivel_pedido"])
        from compras.demo import cargar_compras

        cargar_compras(rubro)  # antes de las ventas: así venden con el costo promedio de lo comprado
        from ventas.demo import cargar_ventas
        from ventas.models import Venta

        # en restaurante casi todo pasa por las mesas: en el mostrador, pocas ventas por día
        nv = cargar_ventas(dias=14, por_dia=(3, 7)) if rubro == Rubro.RESTAURANTE else cargar_ventas()
        from clientes.demo import cargar_clientes

        cargar_clientes()
        if rubro == Rubro.RESTAURANTE:
            from mesas.demo import cargar_mesas

            cargar_mesas()
            from reservas.demo import cargar_reservas

            cargar_reservas()
            from productos.demo import marcar_agotados_demo

            marcar_agotados_demo()
            nv = Venta.objects.count()
        if rubro == Rubro.PELUQUERIA:
            from citas.demo import cargar_citas

            cargar_citas()
        if rubro == Rubro.ACADEMIA:
            from cobranzas.demo import cargar_cobranzas

            cargar_cobranzas()
        from personal.demo import cargar_personal

        cargar_personal(rubro)  # después de las mesas: ahí se crea el usuario del mozo
        from facturacion.demo import cargar_comprobantes

        cargar_comprobantes()
        if rubro == Rubro.RESTAURANTE:  # dos cajas: la principal (series generales) y la barra con su propia serie
            from caja.models import PuntoCaja, SesionCaja

            principal, _ = PuntoCaja.objects.get_or_create(nombre="Caja principal", defaults={"orden": 10})
            PuntoCaja.objects.get_or_create(nombre="Barra", defaults={"orden": 20, "serie_boleta": "B002", "serie_nc_boleta": "BC02"})
            SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA, punto__isnull=True).update(punto=principal)
        self.stdout.write(self.style.SUCCESS(
            f"Datos de ejemplo listos ({a.get_rubro_display()}, {n} productos, {nv} ventas). Usuarios: {', '.join(x[0] for x in USUARIOS)}"
            f"{', mozo' if rubro == Rubro.RESTAURANTE else ''}{', estilista' if rubro == Rubro.PELUQUERIA else ''} (clave {CLAVE})."))
