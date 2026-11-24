"""Cobrar por separado unidades de una misma línea (4 gaseosas, cada uno paga la suya) y platos «para llevar» dentro de
una mesa (se empacan, pero se cobran en la misma cuenta)."""
import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica

from .models import ItemCuenta, Mesa, Zona
from .servicios import MesaError, abrir_cuenta, agregar, cobrar, cotizar, enviar_cocina

D = Decimal


class DividirYLlevarTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"], "vender_sin_caja": True})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("50"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        self.gas = asegurar_variante_unica(Producto.objects.create(nombre="Inca Kola", precio=D("4"), maneja_stock=False))
        self.lomo = asegurar_variante_unica(Producto.objects.create(nombre="Lomo saltado", precio=D("25"), maneja_stock=False))

    def test_cobrar_algunas_unidades_de_una_linea(self):
        c = abrir_cuenta(self.mozo, self.mesa, 4)
        agregar(c, [{"variante": self.gas.pk, "cantidad": 4}, {"variante": self.lomo.pk, "cantidad": 1}], self.mozo)
        enviar_cocina(c)
        gas = c.items.get(variante=self.gas)
        # cotizar no deja la línea partida
        _, total = cotizar(c, [{"id": gas.pk, "cantidad": "1"}])
        self.assertEqual((total, c.items.count()), (D("4"), 2))
        with self.assertRaises(MesaError):
            cobrar(c, self.cajero, [{"metodo": "EFE", "monto": "4"}], [{"id": gas.pk, "cantidad": "0"}])
        v1 = cobrar(c, self.cajero, [{"metodo": "YAP", "monto": "4"}], [{"id": gas.pk, "cantidad": "1"}])
        self.assertEqual(v1.total, D("4"))
        gas.refresh_from_db()
        self.assertEqual((gas.cantidad, gas.venta_id), (D("3"), None))  # quedan 3 por cobrar en la misma línea
        pagada = c.items.get(venta=v1)
        self.assertEqual((pagada.cantidad, pagada.enviado_en is not None), (D("1"), True))  # cocina no la vuelve a ver
        # desde la pantalla: 2 gaseosas más (de 3) y el lomo
        self.client.force_login(self.cajero)
        datos = {"items": [{"id": gas.pk, "cantidad": 2}, str(c.items.get(variante=self.lomo).pk)],
                 "pagos": [{"metodo": "EFE", "monto": "33"}], "token": "t1"}
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps(datos), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertTrue(c.abierta)
        self.assertEqual(c.total_por_cobrar, D("4"))  # falta 1 gaseosa
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps({"pagos": [{"metodo": "EFE", "monto": "4"}], "token": "t2"}),
                             content_type="application/json")
        c.refresh_from_db()
        self.assertFalse(c.abierta)
        self.assertEqual(sum(i.cantidad for i in c.items.filter(variante=self.gas)), D("4"))
        # la pantalla trae la cantidad de cada línea para elegir cuántas paga
        self.assertContains(self.client.get(reverse("mesas:cuenta", args=[c.pk])), "Ya cobrado")

    def test_para_llevar_en_la_mesa(self):
        c = abrir_cuenta(self.mozo, self.mesa, 2)
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 1}, {"variante": self.lomo.pk, "cantidad": 1, "llevar": True}], self.mozo)
        self.assertEqual(sorted(c.items.values_list("llevar", flat=True)), [False, True])  # no se juntan en una línea
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 1, "llevar": True}], self.mozo)
        self.assertEqual(c.items.get(llevar=True).cantidad, D("2"))
        self.client.force_login(self.mozo)
        self.assertContains(self.client.get(reverse("mesas:cuenta", args=[c.pk])), "llevar</span>")
        enviar_cocina(c)
        self.client.force_login(self.cajero)
        comanda = self.client.get(reverse("mesas:comanda", args=[c.pk]))
        self.assertContains(comanda, "PARA LLEVAR")
        v = cobrar(c, self.cajero, [{"metodo": "EFE", "monto": "75"}])
        self.assertEqual(v.total, D("75"))  # todo en la misma cuenta
        # sin mesa (pedido para llevar) la marca no aplica
        c2 = abrir_cuenta(self.mozo, None, nombre="Juan")
        agregar(c2, [{"variante": self.lomo.pk, "cantidad": 1, "llevar": True}], self.mozo)
        self.assertFalse(ItemCuenta.objects.get(cuenta=c2).llevar)
