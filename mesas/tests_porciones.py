"""Porciones del día (la cocina dice cuántas hay; se avisa en amarillo y rojo; con 0 queda agotado) y mozos (quién pidió
cada plato y pasar la mesa a otro mozo)."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir
from core.models import Ajustes, Bitacora
from productos.models import Producto
from productos.servicios import asegurar_variante_unica, con_pocas_porciones, nivel_porciones, poner_porciones
from ventas.servicios import VentaInvalida, registrar_venta

from .models import Mesa, Zona
from .servicios import MesaError, abrir_cuenta, agregar, cambiar_cantidad, cobrar, enviar_cocina, quitar

D = Decimal


class PorcionesYMozosTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"], "vender_sin_caja": True})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123", first_name="Ana")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.otro = User.objects.create_user("luis", password="x-clave-123", first_name="Luis")
        self.otro.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("50"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        self.ceviche = Producto.objects.create(nombre="Ceviche", precio=D("30"), maneja_stock=False)
        self.v = asegurar_variante_unica(self.ceviche)

    def quedan(self):
        self.ceviche.refresh_from_db()
        return self.ceviche.porciones_hoy

    def test_porciones_avisos_y_agotado(self):
        poner_porciones(self.ceviche, 6)
        c = abrir_cuenta(self.mozo, self.mesa, 2)
        agregar(c, [{"variante": self.v.pk, "cantidad": 2}], self.mozo)
        self.assertEqual((self.quedan(), nivel_porciones(4)), (4, "pocas"))
        self.assertEqual([p.nombre for p in con_pocas_porciones()], ["Ceviche"])
        with self.assertRaisesMessage(MesaError, "solo quedan 4"):
            agregar(c, [{"variante": self.v.pk, "cantidad": 5}], self.mozo)
        item = c.items.get()
        cambiar_cantidad(item, 1)  # aún no se envía: +1 descuenta, −1 devuelve
        self.assertEqual(self.quedan(), 3)
        cambiar_cantidad(item, -1)
        self.assertEqual(self.quedan(), 4)
        item.refresh_from_db()
        quitar(item, self.mozo)  # sin enviar: las porciones vuelven
        self.assertEqual(self.quedan(), 6)
        agregar(c, [{"variante": self.v.pk, "cantidad": 2}], self.mozo)
        enviar_cocina(c)
        quitar(c.items.get(), self.cajero, "se equivocó", puede_anular=True)  # ya se preparó: no vuelven
        self.assertEqual(self.quedan(), 4)
        # en Vender también descuenta; con 0 queda agotado solo
        registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "4"}], [{"metodo": "EFE", "monto": "120"}])
        self.ceviche.refresh_from_db()
        self.assertTrue(self.ceviche.agotado)
        self.assertEqual(nivel_porciones(0), "agotado")
        with self.assertRaisesMessage(VentaInvalida, "agotado"):
            registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "30"}])
        # sin límite otra vez (o al día siguiente)
        poner_porciones(self.ceviche, None)
        self.ceviche.refresh_from_db()
        self.assertFalse(self.ceviche.agotado)
        self.ceviche.porciones, self.ceviche.porciones_dia = 0, timezone.localdate().replace(year=2020)
        self.ceviche.save()
        self.assertIsNone(self.quedan())

    def test_pantallas_de_porciones(self):
        self.client.force_login(self.cajero)
        self.client.post(reverse("productos:agotados"), {"porciones_producto": self.ceviche.pk, "porciones": "2"})
        self.assertEqual(self.quedan(), 2)
        r = self.client.get(reverse("productos:agotados"))
        self.assertContains(r, "Quedan 2")
        self.assertContains(self.client.get(reverse("core:inicio")), "Quedan pocas porciones")
        self.assertContains(self.client.get(reverse("ventas:pos")), '"qn": "muy_pocas"')

    def test_quien_pidio_y_pasar_mesa(self):
        c = abrir_cuenta(self.mozo, self.mesa, 2)
        agregar(c, [{"variante": self.v.pk, "cantidad": 1}], self.mozo)
        agregar(c, [{"variante": self.v.pk, "cantidad": 1, "nota": "sin ají"}], self.otro)  # un compañero ayuda
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("mesas:cuenta", args=[c.pk]))
        self.assertContains(r, "pidió Luis")
        self.assertContains(r, "Pasar la mesa")
        self.client.post(reverse("mesas:pasar_mozo", args=[c.pk]), {"mozo": self.otro.pk})
        c.refresh_from_db()
        self.assertEqual(c.mozo, self.otro)
        self.assertTrue(Bitacora.objects.filter(accion="mesa.mozo").exists())
        # el anterior ya no puede pasarla (no es su mesa ni cobra)
        r = self.client.post(reverse("mesas:pasar_mozo", args=[c.pk]), {"mozo": self.mozo.pk})
        self.assertEqual(r.status_code, 403)
        enviar_cocina(c)
        v = cobrar(c, self.cajero, [{"metodo": "EFE", "monto": "60"}])
        self.assertEqual(v.atendio, self.otro)  # la venta cuenta para quien tiene la mesa al cobrar
