"""Sin el módulo de facturación: el cliente pide boleta o factura al cobrar, el negocio la hace aparte, anota su número
y se la manda por WhatsApp. Con el módulo, el celular sirve para mandarle su comprobante."""
import json
from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica

from .models import Venta


class PorHacerTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["facturacion"], "nombre": "Pollería Rosa"})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("0"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="1/4 pollo", precio=D("20"), maneja_stock=False))
        self.client.force_login(self.cajero)

    def _vender(self, comprobante):
        datos = {"items": [{"variante": self.v.pk, "cantidad": "1"}], "pagos": [{"metodo": "EFE", "monto": "20"}], "comprobante": comprobante}
        return self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")

    def test_pide_factura_se_hace_aparte_y_se_envia(self):
        self.assertContains(self.client.get(reverse("ventas:pos")), 'data-aparte="1"')
        r = self._vender({"tipo": "F", "doc": "20100000009", "nombre": "EMPRESA SAC", "direccion": ""})
        self.assertContains(r, "fiscal", status_code=400)
        r = self._vender({"tipo": "F", "doc": "20100000009", "nombre": "EMPRESA SAC", "direccion": "Av. Lima 1", "celular": "12"})
        self.assertContains(r, "celular", status_code=400)
        r = self._vender({"tipo": "F", "doc": "20100000009", "nombre": "EMPRESA SAC", "direccion": "Av. Lima 1", "celular": "987 654 321"})
        self.assertEqual(r.status_code, 200, r.content)
        v = Venta.objects.get()
        self.assertEqual((v.pide_comprobante, v.cliente_documento, v.cliente_direccion, v.cliente_celular), ("F", "20100000009", "Av. Lima 1", "987 654 321"))
        self.assertTrue(v.comprobante_por_hacer)
        self.assertContains(self.client.get(reverse("ventas:ticket", args=[v.pk])), "Boletas y facturas por hacer")
        self.assertContains(self.client.get(reverse("core:inicio")), "por hacer")
        lista = self.client.get(reverse("ventas:por_hacer"))
        self.assertContains(lista, "EMPRESA SAC")
        self.assertContains(lista, "Ya la hice")
        r = self.client.post(reverse("ventas:por_hacer"), {"venta": v.pk, "numero": "f001-45"})
        hechos = self.client.get(r.url)
        self.assertContains(hechos, "F001-45")
        self.assertContains(hechos, "wa.me/51987654321")
        v.refresh_from_db()
        self.assertFalse(v.comprobante_por_hacer)
        self.assertNotContains(self.client.get(reverse("ventas:por_hacer")), "EMPRESA SAC")
        self.assertEqual(self.client.get(reverse("ventas:por_hacer") + "?excel=1")["Content-Type"][:30], "application/vnd.openxmlformats")

    def test_nota_de_venta_y_boleta_aparte(self):
        self._vender(None)
        self._vender({"tipo": "N", "celular": "987654321"})  # nota de venta: solo guarda el celular
        self._vender({"tipo": "B", "doc": "", "nombre": ""})
        ventas = list(Venta.objects.order_by("id"))
        self.assertEqual([v.pide_comprobante for v in ventas], ["", "", "B"])
        self.assertEqual(ventas[1].cliente_celular, "987654321")
        self.assertIn("wa.me/51987654321", self.client.get(reverse("ventas:ticket", args=[ventas[1].pk])).content.decode())
        self.assertContains(self.client.get(reverse("ventas:por_hacer")), "Cliente sin nombre")
