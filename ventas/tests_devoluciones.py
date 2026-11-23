"""Devoluciones parciales: stock, dinero, deuda, nota de crédito parcial, reportes netos y permisos."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.models import MovimientoCaja
from caja.servicios import abrir, calcular, gastos
from core.models import Ajustes, Bitacora
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock

from .devoluciones import devolver, lineas, por_que_no
from .models import Devolucion, Venta
from .servicios import VentaInvalida, anular_venta, registrar_venta

D = Decimal


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.polo = asegurar_variante_unica(Producto.objects.create(nombre="Polo", precio=D("30"), costo=D("12")))
        self.gorra = asegurar_variante_unica(Producto.objects.create(nombre="Gorra", precio=D("20"), costo=D("8")))
        for v in (self.polo, self.gorra):
            mover_stock(v, 10, MovimientoStock.Tipo.INGRESO, costo_unitario=v.producto.costo)

    def vender(self, pagos=None, descuento=0, **kw):
        return registrar_venta(self.jefe, [{"variante": self.polo.pk, "cantidad": "2"}, {"variante": self.gorra.pk, "cantidad": "1"}],
                               pagos or [{"metodo": "EFE", "monto": "80"}], descuento=descuento, **kw)

    def item(self, venta, variante):
        return venta.items.get(variante=variante).pk


class DevolucionTests(Base):
    def test_parcial_con_descuento_stock_merma_y_caja(self):
        v = self.vender(pagos=[{"metodo": "EFE", "monto": "72"}], descuento="8", puede_descontar=True, descuento_motivo="cliente frecuente")
        self.assertEqual(v.total, D("72.00"))  # 80 − 8: cada sol vale 0.90
        caja = abrir(self.jefe, D("100"))
        d = devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}, {"item": self.item(v, self.gorra), "cantidad": "1", "al_stock": False}],
                     "CAJ", self.jefe, "talla equivocada")
        self.assertEqual(d.total, D("45.00"))  # 30 × 0.9 + 20 × 0.9
        self.polo.refresh_from_db(); self.gorra.refresh_from_db()
        self.assertEqual((self.polo.stock, self.gorra.stock), (D("9"), D("9")))  # la gorra entró y salió como merma
        self.assertTrue(MovimientoStock.objects.filter(variante=self.gorra, tipo="SAL", nota__startswith="Merma por devolución").exists())
        self.assertEqual(calcular(caja)["esperado"], D("55.00"))  # salió de mi caja
        self.assertEqual(d.movimiento.categoria, MovimientoCaja.Categoria.DEVOLUCION)
        hoy = timezone.localdate()
        self.assertEqual(gastos(hoy, hoy)["total"], D("0"))  # una devolución no es un gasto
        self.assertTrue(Bitacora.objects.filter(accion="venta.devolucion").exists())
        # lo que queda: el otro polo; devolverlo cuadra exacto con lo cobrado
        self.assertEqual([l["queda"] for l in lineas(v)], [D("1"), D("0")])
        d2 = devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}], "FUE", self.jefe, "otro más")
        self.assertEqual(d.total + d2.total, v.total)
        self.assertIsNone(d2.movimiento.sesion)
        self.assertEqual(por_que_no(v), "Ya se devolvió todo lo de esta venta.")
        with self.assertRaisesMessage(VentaInvalida, "tiene devoluciones"):
            anular_venta(v, self.jefe, "x")

    def test_limites(self):
        v = self.vender()
        with self.assertRaisesMessage(VentaInvalida, "solo se pueden devolver 2"):
            devolver(v, [{"item": self.item(v, self.polo), "cantidad": "3"}], "FUE", self.jefe, "x")
        with self.assertRaisesMessage(VentaInvalida, "motivo"):
            devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}], "FUE", self.jefe, "")
        with self.assertRaisesMessage(VentaInvalida, "abre tu caja"):
            devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}], "CAJ", self.cajero, "x")
        Venta.objects.filter(pk=v.pk).update(fecha=timezone.now() - timedelta(days=31))
        v.refresh_from_db()
        self.assertIn("30 días", por_que_no(v))

    def test_descuenta_de_la_deuda(self):
        from clientes.models import Cliente

        rosa = Cliente.objects.create(nombre="Rosa", limite_credito=D("500"))
        v = self.vender(pagos=[{"metodo": "CRE", "monto": "80"}], cliente_id=rosa.pk, puede_fiar=True)
        self.assertEqual(rosa.saldo, D("80.00"))
        d = devolver(v, [{"item": self.item(v, self.gorra), "cantidad": "1"}], "DEU", self.jefe, "no le quedó")
        self.assertEqual((d.abono.metodo, d.abono.get_metodo_display()), ("DEV", "Devolución"))
        self.assertEqual(Cliente.objects.get(pk=rosa.pk).saldo, D("60.00"))

    def test_nota_de_credito_parcial(self):
        from facturacion.models import Comprobante, Config
        from facturacion.servicios import crear

        Config.objects.update_or_create(pk=1, defaults={"proveedor": "PRU"})
        v = self.vender()
        cp = crear(v, {"tipo": "B", "doc": "", "nombre": "", "direccion": ""}, self.jefe)
        d = devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}], "FUE", self.jefe, "talla")
        nc = d.nota_credito
        self.assertEqual((nc.tipo, nc.tipo_nota, nc.modifica_id, nc.total), (Comprobante.Tipo.NOTA_CREDITO, 7, cp.pk, D("30.00")))
        self.assertEqual(len(nc.detalle), 1)
        cp.refresh_from_db()
        self.assertFalse(cp.anulado)  # una devolución parcial no anula la boleta

    def test_reportes_netos(self):
        from reportes.servicios import productos, resumen

        v = self.vender()
        hoy = timezone.localdate()
        antes = resumen(hoy, hoy)
        devolver(v, [{"item": self.item(v, self.polo), "cantidad": "1"}], "FUE", self.jefe, "talla")
        r = resumen(hoy, hoy)
        self.assertEqual((r["bruto"], r["devuelto"], r["total"]), (D("80.00"), D("30.00"), D("50.00")))
        self.assertEqual(r["ganancia"], antes["ganancia"] - D("18.00"))  # 30 devueltos − 12 de costo que volvió
        polo = next(p for p in productos(hoy, hoy) if p["nombre"] == "Polo")
        self.assertEqual((polo["cantidad"], polo["total"]), (D("1"), D("30.00")))

    def test_pantalla_y_autorizacion(self):
        v = registrar_venta(self.cajero, [{"variante": self.polo.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "30"}])
        abrir(self.cajero, D("50"))
        self.client.force_login(self.cajero)
        self.assertContains(self.client.get(reverse("ventas:ticket", args=[v.pk])), "Devolver productos")
        url = reverse("ventas:devolver", args=[v.pk])
        r = self.client.get(url)
        self.assertContains(r, "Autoriza un supervisor")
        datos = {f"c_{v.items.get().pk}": "1", "reembolso": "CAJ", "motivo": "fallado"}
        r = self.client.post(url, datos, follow=True)
        self.assertContains(r, "Necesita autorización")
        self.assertFalse(Devolucion.objects.exists())
        r = self.client.post(url, {**datos, "sup_usuario": "jefe", "sup_clave": "x-clave-123"}, follow=True)
        self.assertContains(r, "Devolución registrada: S/ 30.00")
        d = Devolucion.objects.get()
        self.assertEqual((d.usuario, d.autorizo), (self.cajero, self.jefe))
        self.assertNotContains(r, "Anular venta")
        self.assertContains(self.client.get(reverse("ventas:lista")), "Devolución")
