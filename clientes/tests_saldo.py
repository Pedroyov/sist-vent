"""Saldo a favor: entra por una devolución, se usa para pagar, vuelve si se anula y se puede devolver en efectivo."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir, calcular
from core.models import Ajustes, Bitacora
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock
from ventas.conciliacion import cobros
from ventas.devoluciones import devolver
from ventas.servicios import VentaInvalida, anular_venta, registrar_venta

from .models import Cliente, MovimientoSaldo
from .saldo import SaldoError, reintegrar, saldo_a_favor

D = Decimal


class SaldoTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True, "metodos_pago": ["EFE", "YAP"]})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.polo = asegurar_variante_unica(Producto.objects.create(nombre="Polo M", precio=D("30"), costo=D("12")))
        mover_stock(self.polo, 10, MovimientoStock.Tipo.INGRESO)
        self.rosa = Cliente.objects.create(nombre="Rosa", tipo_documento="DNI", numero_documento="44556677")

    def vender(self, pagos, cliente=True):
        return registrar_venta(self.jefe, [{"variante": self.polo.pk, "cantidad": "1"}], pagos, cliente_id=self.rosa.pk if cliente else None)

    def test_cambio_de_talla(self):
        v = self.vender([{"metodo": "EFE", "monto": "30"}])
        d = devolver(v, [{"item": v.items.get().pk, "cantidad": "1"}], "SAL", self.jefe, "talla M por L")
        self.assertEqual(saldo_a_favor(self.rosa), D("30.00"))
        self.assertIsNone(d.movimiento)  # no salió dinero de ninguna caja
        caja = abrir(self.jefe, D("100"))
        # el nuevo polo se paga con el saldo, aunque el negocio no tenga «Saldo a favor» entre sus métodos
        v2 = self.vender([{"metodo": "SAL", "monto": "20"}, {"metodo": "EFE", "monto": "10"}])
        self.assertEqual(saldo_a_favor(self.rosa), D("10.00"))
        self.assertEqual(calcular(caja)["esperado"], D("110.00"))  # solo el efectivo entra al cajón
        hoy = timezone.localdate()
        self.assertNotIn((hoy, "SAL"), cobros(hoy, hoy, ["EFE", "YAP", "PLI", "TAR", "TRA"]))
        with self.assertRaisesMessage(VentaInvalida, "tiene S/ 10.00 de saldo a favor"):
            self.vender([{"metodo": "SAL", "monto": "30"}])
        with self.assertRaisesMessage(VentaInvalida, "elige al cliente"):
            self.vender([{"metodo": "SAL", "monto": "5"}, {"metodo": "EFE", "monto": "25"}], cliente=False)
        anular_venta(v2, self.jefe, "se equivocó")
        self.assertEqual(saldo_a_favor(self.rosa), D("30.00"))  # el saldo vuelve
        self.assertTrue(MovimientoSaldo.objects.get(venta=v2, tipo="USO").anulado)

    def test_devolver_en_efectivo_y_pantallas(self):
        v = self.vender([{"metodo": "EFE", "monto": "30"}])
        devolver(v, [{"item": v.items.get().pk, "cantidad": "1"}], "SAL", self.jefe, "no le gustó")
        with self.assertRaisesMessage(SaldoError, "abre tu caja"):
            reintegrar(self.rosa, "10", self.jefe, "se muda")
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("clientes:detalle", args=[self.rosa.pk]))
        self.assertContains(r, "Saldo a favor")
        self.assertContains(r, "Devolverlo en efectivo")
        r = self.client.get(reverse("clientes:buscar"), {"q": "Rosa"})
        self.assertEqual(r.json()["resultados"][0]["favor"], "30.00")
        caja = abrir(self.jefe, D("50"))
        self.client.post(reverse("clientes:devolver_saldo", args=[self.rosa.pk]), {"monto": "30", "motivo": "se muda"})
        self.assertEqual(saldo_a_favor(self.rosa), D("0.00"))
        self.assertEqual(calcular(caja)["esperado"], D("20.00"))
        self.assertTrue(Bitacora.objects.filter(accion="cliente.saldo_devuelto").exists())
        self.assertContains(self.client.get(reverse("ventas:pos")), '"id": "SAL"')
