"""Compras sin proveedor registrado («Proveedor varios»), el menú «Compras y gastos», la cámara para escanear y la guía
paso a paso de la ayuda."""
from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.ayuda import AYUDA, GUIA
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica

from .models import Compra, Proveedor
from .servicios import PROVEEDOR_VARIOS, CompraError, registrar_compra


class ProveedorVariosTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": []})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(self.jefe)
        self.libre = [{"variante": None, "descripcion": "Verduras del mercado", "cantidad": "1", "costo": "80"}]

    def test_compra_sin_proveedor_va_a_proveedor_varios(self):
        c = registrar_compra(self.jefe, None, self.libre, "SIN", pago="fuera")
        c2 = registrar_compra(self.jefe, None, self.libre, "SIN", pago="fuera")
        self.assertEqual((c.proveedor.nombre, c2.proveedor_id), (PROVEEDOR_VARIOS, c.proveedor_id))  # uno solo
        with self.assertRaisesMessage(CompraError, "a quién le debes"):
            registrar_compra(self.jefe, None, self.libre, "SIN", credito=True)
        with self.assertRaisesMessage(CompraError, "a quién le debes"):
            registrar_compra(self.jefe, c.proveedor, self.libre, "SIN", credito=True)
        # desde la pantalla: sin elegir proveedor y con el aviso de Gastos
        r = self.client.get(reverse("compras:nueva"))
        self.assertContains(r, "Proveedor varios (mercado, sin registrar)")
        self.assertContains(r, "Eso va en")
        import json

        r = self.client.post(reverse("compras:nueva"), {"proveedor": "", "documento": "SIN", "fecha": c.fecha.isoformat(), "pago": "fuera",
                                                      "items": json.dumps(self.libre), "token": "t-1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Compra.objects.filter(proveedor__nombre=PROVEEDOR_VARIOS).count(), 3)
        self.assertEqual(Proveedor.objects.filter(nombre=PROVEEDOR_VARIOS).count(), 1)

    def test_menu_lateral_camara_y_guias(self):
        r = self.client.get(reverse("core:inicio"))
        self.assertContains(r, "COMPRAS Y GASTOS")
        self.assertContains(r, reverse("compras:proveedores"))
        self.assertContains(r, "js/escaner.js")
        p = asegurar_variante_unica(Producto.objects.create(nombre="Inca Kola", precio=D("4")))
        self.assertContains(self.client.get(reverse("productos:editar", args=[p.producto_id])), "data-escaner")
        self.assertEqual([k for k in GUIA if k not in AYUDA], [])  # cada guía es de una pantalla con ayuda
        r = self.client.get(reverse("caja:gastos"))
        self.assertContains(r, "Paso a paso")
        self.assertContains(r, "Ojo")
