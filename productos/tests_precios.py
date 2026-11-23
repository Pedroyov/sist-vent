"""Listas de precios: precio por cantidad, por tipo de cliente (lista) o ambos; gana el más bajo y lo decide el servidor."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente
from core.models import Ajustes, Bitacora
from ventas.servicios import VentaInvalida, registrar_venta

from .models import ListaPrecios, PrecioEspecial, Producto, Variante
from .servicios import asegurar_variante_unica

D = Decimal


class ListasDePreciosTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True, "funciones_inactivas": [],
                                                         "metodos_pago": ["EFE", "YAP"]})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.polo = Producto.objects.create(nombre="Polo", precio=D("30"), maneja_stock=False)
        self.s = Variante.objects.create(producto=self.polo, nombre="S")
        self.m = Variante.objects.create(producto=self.polo, nombre="M")
        self.xl = Variante.objects.create(producto=self.polo, nombre="XL", precio=D("35"))  # precio propio
        self.gaseosa = asegurar_variante_unica(Producto.objects.create(nombre="Gaseosa", precio=D("2.50"), maneja_stock=False))
        self.mayorista = ListaPrecios.objects.create(nombre="Mayorista", porcentaje=D("10"))
        self.tienda = Cliente.objects.create(nombre="Bodega Luz", tipo_documento="DNI", numero_documento="40112233", lista=self.mayorista)
        PrecioEspecial.objects.create(producto=self.polo, desde=6, precio=D("26"))
        PrecioEspecial.objects.create(producto=self.polo, lista=self.mayorista, desde=12, precio=D("22"))
        PrecioEspecial.objects.create(producto=self.gaseosa.producto, lista=self.mayorista, precio=D("2.00"))

    def vender(self, items, total, cliente=None, usuario=None):
        return registrar_venta(usuario or self.cajero, [{"variante": v.pk, "cantidad": str(q)} for v, q in items],
                               [{"metodo": "YAP", "monto": str(total)}], cliente_id=cliente.pk if cliente else None)

    def test_por_cantidad_cuenta_todo_el_producto(self):
        v = self.vender([(self.s, 3), (self.m, 2)], "150.00")  # 5 polos: precio normal
        self.assertEqual(v.items.first().precio_regla, "")
        v = self.vender([(self.s, 3), (self.m, 3), (self.xl, 1)], "191.00")  # 7 polos: S y M a 26; XL tiene precio propio
        filas = {i.variante_id: (i.precio_unitario, i.precio_regla) for i in v.items.all()}
        self.assertEqual(filas[self.s.pk], (D("26.00"), "Precio por cantidad"))
        self.assertEqual(filas[self.xl.pk], (D("35.00"), ""))
        self.assertFalse(Bitacora.objects.filter(accion="venta.precio").exists())  # no es un cambio de precio a mano
        with self.assertRaisesMessage(VentaInvalida, "el vuelto solo sale del efectivo"):  # el servidor no cobra el precio normal
            self.vender([(self.s, 6)], "180.00")

    def test_tipo_de_cliente(self):
        v = self.vender([(self.s, 1), (self.xl, 1), (self.gaseosa, 2)], "62.50", cliente=self.tienda)
        filas = {i.variante_id: (i.precio_unitario, i.precio_regla) for i in v.items.all()}
        self.assertEqual(filas[self.s.pk], (D("27.00"), "Precio Mayorista"))      # 10 % menos
        self.assertEqual(filas[self.xl.pk], (D("31.50"), "Precio Mayorista"))     # el % también a las variantes con precio propio
        self.assertEqual(filas[self.gaseosa.pk], (D("2.00"), "Precio Mayorista"))  # precio fijo de la lista: gana el más bajo
        v = self.vender([(self.s, 12)], "264.00", cliente=self.tienda)  # mayorista desde 12: 22 c/u
        self.assertEqual(v.items.get().precio_unitario, D("22.00"))
        self.vender([(self.s, 1)], "30.00")  # sin cliente: precio normal
        self.mayorista.activa = False
        self.mayorista.save()
        self.vender([(self.s, 1)], "30.00", cliente=self.tienda)  # lista inactiva: precio normal

    def test_funcion_apagada_no_cambia_nada(self):
        Ajustes.objects.filter(pk=1).update(funciones_inactivas=["precios"])
        v = self.vender([(self.s, 12)], "360.00", cliente=self.tienda)
        self.assertEqual(v.items.get().precio_regla, "")
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("productos:detalle", args=[self.polo.pk]))
        self.assertNotContains(r, "Precios especiales")

    def test_pantallas(self):
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("productos:detalle", args=[self.polo.pk]))
        self.assertContains(r, "Precios especiales")
        url = reverse("productos:precios", args=[self.gaseosa.producto.pk])
        r = self.client.post(url, {"accion": "agregar", "desde": "1", "precio": "2.20"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "pon desde cuántas unidades")  # para todos solo por cantidad
        self.client.post(url, {"accion": "agregar", "desde": "6", "precio": "2.30"}, HTTP_HX_REQUEST="true")
        pe = PrecioEspecial.objects.get(producto=self.gaseosa.producto, lista=None)
        self.assertEqual((pe.desde, pe.precio), (D("6"), D("2.30")))
        self.assertTrue(Bitacora.objects.filter(accion="producto.precio").exists())
        r = self.client.post(url, {"accion": "agregar", "desde": "10", "precio": "3"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "menor que el normal")
        self.client.post(url, {"accion": "quitar", "especial": pe.pk}, HTTP_HX_REQUEST="true")
        self.assertFalse(PrecioEspecial.objects.filter(pk=pe.pk).exists())
        # listas
        self.client.post(reverse("productos:listas_precios"), {"nombre": "Revendedor", "porcentaje": "5", "activa": "on"})
        self.assertTrue(ListaPrecios.objects.filter(nombre="Revendedor").exists())
        self.assertContains(self.client.get(reverse("productos:listas_precios")), "1 cliente")
        # el cliente se marca con su lista (queda en la bitácora) y el cobro la recibe
        otro = Cliente.objects.create(nombre="Ana Ríos")
        self.client.post(reverse("clientes:editar", args=[otro.pk]), {"tipo_documento": "SD", "nombre": "Ana Ríos",
                                                                      "limite_credito": "0", "lista": self.mayorista.pk, "activo": "on"})
        otro.refresh_from_db()
        self.assertEqual(otro.lista, self.mayorista)
        self.assertTrue(Bitacora.objects.filter(accion="cliente.lista").exists())
        self.assertEqual(self.client.get(reverse("clientes:buscar"), {"q": "Ana"}).json()["resultados"][0]["lista"], self.mayorista.pk)
        self.assertContains(self.client.get(reverse("ventas:pos")), "var COTIZA = true")
        # Vender pide los precios al servidor: con el cliente mayorista, la línea dice por qué
        r = self.client.post(reverse("ventas:cotizar"), {"items": [{"variante": self.s.pk, "cantidad": "1"}], "cliente_id": otro.pk},
                             content_type="application/json")
        self.assertEqual((r.json()["subtotal"], r.json()["lineas"][0]["regla"]), ("27.00", "Precio Mayorista"))
