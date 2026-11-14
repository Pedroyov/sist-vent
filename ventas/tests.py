import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, generar_variantes, mover_stock

from .models import Venta
from .servicios import VentaInvalida, anular_venta, registrar_venta

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="x-clave-123", is_superuser=True)
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.vendedor = User.objects.create_user("vendedor", password="x-clave-123")
        self.vendedor.groups.add(Group.objects.get(name="Vendedor"))
        self.gaseosa = Producto.objects.create(nombre="Gaseosa", precio=D("2.50"), costo=D("1.80"))
        self.vg = asegurar_variante_unica(self.gaseosa)
        mover_stock(self.vg, 10, MovimientoStock.Tipo.INGRESO)
        self.arroz = Producto.objects.create(nombre="Arroz", precio=D("4.20"), unidad="KG")
        self.va = asegurar_variante_unica(self.arroz)
        self.corte = Producto.objects.create(nombre="Corte", precio=D("25"), tipo="S")
        self.vc = asegurar_variante_unica(self.corte)


class ServicioTests(Base):
    def test_venta_con_vuelto_y_stock(self):
        v = registrar_venta(self.cajero, [{"variante": self.vg.pk, "cantidad": "3"}, {"variante": self.vc.pk, "cantidad": "1"}],
                            [{"metodo": "EFE", "monto": "50"}])
        self.assertEqual((v.total, v.vuelto, v.recibido), (D("32.50"), D("17.50"), D("50")))
        self.assertEqual(v.pagos.get().monto, D("32.50"))
        self.vg.refresh_from_db()
        self.assertEqual(self.vg.stock, D("7"))
        self.assertEqual(v.numero, 1)
        self.assertEqual(registrar_venta(self.cajero, [{"variante": self.vc.pk, "cantidad": "1"}], [{"metodo": "YAP", "monto": "25"}]).numero, 2)

    def test_validaciones(self):
        casos = [
            ([], [{"metodo": "EFE", "monto": "1"}], "No hay productos"),
            ([{"variante": self.vg.pk, "cantidad": "1.5"}], [{"metodo": "EFE", "monto": "10"}], "unidades enteras"),
            ([{"variante": self.vg.pk, "cantidad": "-1"}], [], "valor no permitido"),
            ([{"variante": self.vg.pk, "cantidad": "2"}], [{"metodo": "EFE", "monto": "4"}], "Falta cobrar S/ 1.00"),
            ([{"variante": self.vg.pk, "cantidad": "2"}], [{"metodo": "YAP", "monto": "10"}], "vuelto solo sale del efectivo"),
            ([{"variante": self.vg.pk, "cantidad": "1"}], [{"metodo": "XXX", "monto": "10"}], "Método de pago"),
            ([{"variante": 9999, "cantidad": "1"}], [], "ya no está disponible"),
        ]
        for items, pagos, msg in casos:
            with self.assertRaisesMessage(VentaInvalida, msg):
                registrar_venta(self.cajero, items, pagos)
        self.assertFalse(Venta.objects.exists())

    def test_fraccion_precio_y_descuento(self):
        # sin permiso: se ignora el precio que manda el navegador y no puede dar descuento
        v = registrar_venta(self.cajero, [{"variante": self.va.pk, "cantidad": "1.5", "precio": "0.01"}], [{"metodo": "EFE", "monto": "6.30"}])
        self.assertEqual(v.total, D("6.30"))
        with self.assertRaisesMessage(VentaInvalida, "permiso para dar descuentos"):
            registrar_venta(self.cajero, [{"variante": self.va.pk, "cantidad": "1"}], [], descuento="1")
        v = registrar_venta(self.admin, [{"variante": self.va.pk, "cantidad": "2", "precio": "4.00"}], [{"metodo": "TAR", "monto": "7"}],
                            descuento="1", puede_cambiar_precio=True)
        self.assertEqual((v.subtotal, v.total), (D("8.00"), D("7.00")))
        self.assertTrue(v.items.get().precio_cambiado)

    def test_pago_mixto(self):
        v = registrar_venta(self.cajero, [{"variante": self.vc.pk, "cantidad": "1"}],
                            [{"metodo": "YAP", "monto": "10"}, {"metodo": "EFE", "monto": "20"}])
        self.assertEqual(v.vuelto, D("5"))
        self.assertEqual({p.metodo: p.monto for p in v.pagos.all()}, {"YAP": D("10"), "EFE": D("15")})

    def test_token_evita_doble_venta(self):
        args = ([{"variante": self.vg.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "2.50"}])
        a = registrar_venta(self.cajero, *args, token="abc")
        b = registrar_venta(self.cajero, *args, token="abc")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Venta.objects.count(), 1)

    def test_anular_devuelve_stock(self):
        v = registrar_venta(self.cajero, [{"variante": self.vg.pk, "cantidad": "4"}], [{"metodo": "EFE", "monto": "10"}])
        with self.assertRaises(VentaInvalida):
            anular_venta(v, self.admin, "  ")
        anular_venta(v, self.admin, "Cliente devolvió")
        self.vg.refresh_from_db()
        self.assertEqual(self.vg.stock, D("10"))
        with self.assertRaisesMessage(VentaInvalida, "ya estaba anulada"):
            anular_venta(v, self.admin, "otra vez")

    def test_variante_vendida_no_se_borra(self):
        p = Producto.objects.create(nombre="Polo", precio=D("30"), maneja_stock=False)
        generar_variantes(p, "S, M")
        s = p.variantes.get(nombre="S")
        registrar_venta(self.cajero, [{"variante": s.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "30"}])
        self.client.force_login(self.admin)
        self.client.post(reverse("productos:variante_eliminar", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.activa)
        self.client.post(reverse("productos:eliminar", args=[p.pk]))
        self.assertTrue(Producto.objects.filter(pk=p.pk).exists())


class VistasTests(Base):
    def _vender(self, usuario, cuerpo):
        self.client.force_login(usuario)
        return self.client.post(reverse("ventas:registrar"), json.dumps(cuerpo), content_type="application/json")

    def test_pos_y_registrar(self):
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, "Gaseosa")
        r = self._vender(self.vendedor, {"token": "t1", "items": [{"variante": self.vg.pk, "cantidad": "2"}], "pagos": [{"metodo": "EFE", "monto": "10"}]})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["vuelto"], "5.00")
        r = self.client.get(d["url"])
        self.assertContains(r, "Vuelto")
        self.assertContains(r, "NOTA DE VENTA")
        r = self._vender(self.vendedor, {"items": [], "pagos": []})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse("ventas:registrar"), "no es json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_vendedor_solo_ve_sus_ventas(self):
        mia = registrar_venta(self.vendedor, [{"variante": self.vc.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "25"}])
        ajena = registrar_venta(self.cajero, [{"variante": self.vc.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "25"}])
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(reverse("ventas:ticket", args=[mia.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("ventas:ticket", args=[ajena.pk])).status_code, 403)
        r = self.client.get(reverse("ventas:lista"))
        self.assertContains(r, "Mis ventas")
        self.assertContains(r, mia.numero_str)
        self.assertNotContains(r, ajena.numero_str)
        self.assertEqual(self.client.post(reverse("ventas:anular", args=[mia.pk]), {"motivo": "x"}).status_code, 403)

    def test_lista_resumen_excel_y_anular(self):
        registrar_venta(self.cajero, [{"variante": self.vg.pk, "cantidad": "2"}], [{"metodo": "YAP", "monto": "5"}])
        v = registrar_venta(self.cajero, [{"variante": self.vc.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "25"}])
        self.client.force_login(self.admin)
        r = self.client.get(reverse("ventas:lista"))
        self.assertEqual(r.context["r"]["total"], D("30"))
        self.assertEqual(r.context["r"]["ganancia"], D("30") - D("3.60"))
        self.assertEqual(self.client.get(reverse("ventas:lista") + "?excel=1").status_code, 200)
        self.client.post(reverse("ventas:anular", args=[v.pk]), {"motivo": "Error"})
        r = self.client.get(reverse("ventas:lista") + "?desde=fecha-mala")
        self.assertEqual(r.context["r"]["total"], D("5"))
        self.assertEqual(r.context["r"]["anuladas"], 1)
        self.assertContains(self.client.get(reverse("core:inicio")), "Cobrado hoy")
