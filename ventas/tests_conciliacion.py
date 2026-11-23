"""Conciliación de Yape, Plin, tarjeta y transferencias con el banco, y N° de operación obligatorio."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Ajustes, Bitacora
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock

from .conciliacion import operaciones, para_reportes, pendientes, resumen, totales
from .models import Conciliacion, NoLlego, Pago, Venta
from .servicios import VentaInvalida, anular_venta, registrar_venta

D = Decimal


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123", first_name="Ana")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123", first_name="Luis")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Menú", precio=D("5")))
        mover_stock(self.v, 100, MovimientoStock.Tipo.INGRESO)
        self.hoy = timezone.localdate()

    def vender(self, cantidad, metodo, referencia="", hace=0):
        v = registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": str(cantidad)}],
                            [{"metodo": metodo, "monto": str(5 * cantidad), "referencia": referencia}])
        if hace:
            Venta.objects.filter(pk=v.pk).update(fecha=timezone.now() - timedelta(days=hace))
        return v

    def fiar(self, cliente, cantidad):
        registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": str(cantidad)}], [{"metodo": "CRE", "monto": str(5 * cantidad)}],
                        cliente_id=cliente.pk, puede_fiar=True)


class ConciliacionTests(Base):
    def test_cuadre_no_llego_y_reportes(self):
        self.vender(5, "YAP", "00123")
        chica = self.vender(2, "YAP")
        self.vender(1, "PLI")
        self.vender(4, "EFE")
        anulada = self.vender(3, "YAP")
        anular_venta(anulada, self.jefe, "error")
        t = totales(self.hoy, self.hoy)
        self.assertEqual(t[(self.hoy, "YAP")], {"total": D("35.00"), "n": 2})  # la anulada y el efectivo no cuentan
        self.assertEqual(t[(self.hoy, "PLI")]["total"], D("5.00"))
        fila = resumen(self.hoy, self.hoy)[0]
        self.assertEqual([m["estado"] for m in fila["metodos"]], ["pendiente", "pendiente"])

        self.client.force_login(self.cajero)
        url = reverse("ventas:conciliar_dia", args=[self.hoy.isoformat(), "YAP"])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("ventas:conciliar"))
        self.assertContains(r, "Sin conciliar")
        r = self.client.get(url)
        self.assertContains(r, "00123")
        self.assertNotContains(r, "No llegó</button>")  # primero se escribe lo del banco
        self.client.post(url, {"accion": "guardar", "banco": "25"})
        c = Conciliacion.objects.get(fecha=self.hoy, metodo="YAP")
        self.assertEqual((c.sistema, c.banco, c.diferencia), (D("35.00"), D("25.00"), D("-10.00")))
        self.assertTrue(Bitacora.objects.filter(accion="conciliacion.diferencia").exists())
        # el Yape de S/ 10 no llegó: queda como faltante de quien lo cobró
        pago = Pago.objects.get(venta=chica)
        self.client.post(url, {"accion": "no_llego", "tipo": "venta", "id": pago.pk})
        self.assertTrue(NoLlego.objects.filter(objeto_id=pago.pk, cobro=self.cajero).exists())
        r = self.client.get(url)
        self.assertEqual(r.context["sin_explicar"], D("0.00"))
        rep = para_reportes(self.hoy, self.hoy)
        self.assertEqual(rep["por_cajero"], [{"etiqueta": "Luis", "n": 1, "total": D("10.00")}])
        self.assertContains(self.client.get(reverse("reportes:inicio")), "frente al banco")
        # corregir lo del banco y deshacer el «no llegó» queda en la bitácora
        self.client.post(url, {"accion": "guardar", "banco": "35"})
        c.refresh_from_db()
        self.assertEqual(c.diferencia, D("0"))
        self.assertTrue(Bitacora.objects.filter(accion="conciliacion.cambiada").exists())
        self.client.post(url, {"accion": "quitar", "tipo": "venta", "id": pago.pk})
        self.assertFalse(NoLlego.objects.exists())
        self.assertTrue(Bitacora.objects.filter(accion="pago.no_llego_quitado").exists())
        # una anulación posterior se nota
        anular_venta(chica, self.jefe, "devolución")
        self.assertTrue(resumen(self.hoy, self.hoy)[0]["metodos"][0]["cambio"])
        # un día futuro no se concilia
        mañana = (self.hoy + timedelta(days=1)).isoformat()
        r = self.client.post(reverse("ventas:conciliar_dia", args=[mañana, "YAP"]), {"accion": "guardar", "banco": "1"}, follow=True)
        self.assertContains(r, "todavía no llega")

    def test_pagos_de_fiado_y_aviso_en_el_inicio(self):
        from clientes.models import Cliente
        from clientes.servicios import registrar_abono

        c = Cliente.objects.create(nombre="Rosa", limite_credito=D("500"))
        self.fiar(c, 4)
        a = registrar_abono(c, D("12"), "PLI", self.cajero, referencia="777")
        self.assertIn((self.hoy, "PLI"), totales(self.hoy, self.hoy))
        self.assertEqual(operaciones(self.hoy, "PLI")[0]["referencia"], "777")
        self.assertEqual(operaciones(self.hoy, "PLI")[0]["id"], a.pk)
        self.vender(1, "YAP", hace=4)
        p = pendientes()
        self.assertEqual([(x["metodo"], x["desde"]) for x in p], [("YAP", self.hoy - timedelta(days=4))])
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("core:inicio")), "Yape sin conciliar")
        self.client.force_login(self.cajero)
        self.assertNotContains(self.client.get(reverse("core:inicio")), "sin conciliar")
        Conciliacion.objects.create(fecha=self.hoy - timedelta(days=4), metodo="YAP", sistema=5, banco=5, diferencia=0, usuario=self.jefe)
        self.assertEqual(pendientes(), [])


class OperacionObligatoriaTests(Base):
    def test_yape_y_plin_piden_numero_si_se_enciende(self):
        self.vender(1, "YAP")  # apagado: no hace falta
        Ajustes.objects.filter(pk=1).update(exigir_operacion=True)
        with self.assertRaisesMessage(VentaInvalida, "N° de operación del Yape"):
            self.vender(1, "YAP")
        self.vender(1, "YAP", "4455")
        self.vender(1, "TAR")  # la tarjeta no lo exige
        from clientes.models import Cliente
        from clientes.servicios import ClienteError, registrar_abono

        c = Cliente.objects.create(nombre="Rosa", limite_credito=D("500"))
        self.fiar(c, 4)
        with self.assertRaises(ClienteError):
            registrar_abono(c, D("5"), "PLI", self.cajero)
        registrar_abono(c, D("5"), "PLI", self.cajero, referencia="99")
        self.client.force_login(self.cajero)
        self.assertContains(self.client.get(reverse("ventas:pos")), 'data-operacion="1"')
