"""Monedero: un % de lo pagado vuelve como saldo a favor que vence; lo fiado da monedero al pagarse; se descuenta si se
devuelve o se anula."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica
from ventas.devoluciones import devolver
from ventas.servicios import anular_venta, registrar_venta

from .models import Cliente, MovimientoSaldo
from .saldo import saldo_a_favor, total_a_favor
from .servicios import anular_abono, registrar_abono

D = Decimal


class MonederoTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True, "funciones_inactivas": [], "monedero_porcentaje": D("2"),
                                                         "monedero_dias": 90, "metodos_pago": ["EFE", "YAP", "CRE"]})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.polo = asegurar_variante_unica(Producto.objects.create(nombre="Polo", precio=D("30"), maneja_stock=False))
        self.rosa = Cliente.objects.create(nombre="Rosa", tipo_documento="DNI", numero_documento="44556677")

    def vender(self, cant, pagos, cliente=True):
        return registrar_venta(self.jefe, [{"variante": self.polo.pk, "cantidad": str(cant)}], pagos,
                               cliente_id=self.rosa.pk if cliente else None, puede_fiar=True)

    def test_gana_usa_y_vence(self):
        v = self.vender(2, [{"metodo": "EFE", "monto": "100"}])  # S/ 60 (vuelto 40): gana 1.20
        m = MovimientoSaldo.objects.get(venta=v, tipo="MON")
        self.assertEqual((m.monto, m.vence), (D("1.20"), timezone.localdate() + timedelta(days=90)))
        self.vender(1, [{"metodo": "EFE", "monto": "30"}], cliente=False)  # sin cliente no gana
        self.assertEqual(saldo_a_favor(self.rosa), D("1.20"))
        v2 = self.vender(1, [{"metodo": "SAL", "monto": "1.20"}, {"metodo": "YAP", "monto": "28.80"}])  # lo usa; gana solo por lo pagado
        self.assertEqual(MovimientoSaldo.objects.get(venta=v2, tipo="MON").monto, D("0.58"))
        self.assertEqual(saldo_a_favor(self.rosa), D("0.58"))
        self.assertEqual(saldo_a_favor(self.rosa, hoy=timezone.localdate() + timedelta(days=91)), D("0"))  # lo no usado vence
        self.assertEqual(total_a_favor(), D("0.58"))
        r = self.client
        r.force_login(self.jefe)
        self.assertContains(r.get(reverse("ventas:ticket", args=[v2.pk])), "Ganaste S/ 0.58")
        self.assertContains(r.get(reverse("clientes:detalle", args=[self.rosa.pk])), "Monedero (por su compra)")

    def test_fiado_da_monedero_al_pagarse(self):
        abrir(self.jefe, D("50"))
        self.vender(1, [{"metodo": "CRE", "monto": "30"}])
        self.assertEqual(saldo_a_favor(self.rosa), D("0"))
        a = registrar_abono(self.rosa, D("30"), "EFE", self.jefe)
        self.assertEqual(saldo_a_favor(self.rosa), D("0.60"))
        anular_abono(a, self.jefe, "billete falso")
        self.assertEqual(saldo_a_favor(self.rosa), D("0"))

    def test_devolucion_y_anulacion_lo_descuentan(self):
        v = self.vender(2, [{"metodo": "YAP", "monto": "60"}])  # gana 1.20
        devolver(v, [{"item": v.items.get().pk, "cantidad": "1"}], "FUE", self.jefe, "no le quedó")
        self.assertEqual(saldo_a_favor(self.rosa), D("0.60"))
        v2 = self.vender(1, [{"metodo": "YAP", "monto": "30"}])  # gana 0.60 → 1.20
        v3 = self.vender(1, [{"metodo": "SAL", "monto": "1.20"}, {"metodo": "YAP", "monto": "28.80"}])  # lo gasta; gana 0.58
        anular_venta(v2, self.jefe, "error")  # ya lo usó: solo se descuenta lo que queda, nunca negativo
        self.assertEqual(saldo_a_favor(self.rosa), D("0"))
        self.assertTrue(v3)

    def test_apagado(self):
        Ajustes.objects.filter(pk=1).update(funciones_inactivas=["monedero"])
        self.vender(1, [{"metodo": "EFE", "monto": "30"}])
        self.assertFalse(MovimientoSaldo.objects.exists())
