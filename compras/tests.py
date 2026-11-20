import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.models import MovimientoCaja
from caja.servicios import abrir, anular_gasto, gastos
from core.models import Ajustes
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock

from .models import Compra, Proveedor
from .servicios import (CompraError, anular_compra, deudas_por_proveedor, pagar, pagar_proveedor, registrar_compra,
                        vencen_pronto)

D = Decimal


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": []})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.arroz = asegurar_variante_unica(Producto.objects.create(nombre="Arroz 1 kg", precio=D("6")))
        mover_stock(self.arroz, 10, MovimientoStock.Tipo.INGRESO, costo_unitario=D("4"))
        self.plato = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("28"), maneja_stock=False))
        self.prov = Proveedor.objects.create(nombre="DISTRIBUIDORA LIMA SAC", comercial="Distribuidora Lima", ruc="20100070970", plazo=15)
        self.hoy = timezone.localdate()

    def items(self, cant="10", costo="5", libre=None):
        lista = [{"variante": self.arroz.pk, "cantidad": cant, "costo": costo}]
        if libre:
            lista.append({"variante": None, "descripcion": "Flete", "cantidad": "1", "costo": libre})
        return lista


class ComprasTests(Base):
    def test_contado_de_caja_suma_stock_costo_y_gasto(self):
        s = abrir(self.jefe, D("100"))
        c = registrar_compra(self.jefe, self.prov, self.items(libre="12"), "FAC", "f001", "00045", pago="caja")
        self.assertEqual((c.serie, c.numero, c.total, c.saldo, c.estado), ("F001", "45", D("62"), D("0"), "Pagada"))
        self.assertEqual((c.base, c.igv), (D("52.54"), D("9.46")))
        self.arroz.refresh_from_db()
        self.assertEqual((self.arroz.stock, self.arroz.costo), (D("20"), D("4.50")))  # promedio: 10 a 4 + 10 a 5
        mov = MovimientoStock.objects.filter(referencia="Compra F001-45").get()
        self.assertEqual((mov.tipo, mov.cantidad), ("ING", D("10")))
        pago = s.movimientos.get()
        self.assertEqual((pago.monto, pago.categoria, pago.compra), (D("62"), "PRO", c))
        g = gastos(self.hoy, self.hoy)
        self.assertEqual([f["categoria"] for f in g["filas"]], ["PRO", "CSP"])
        self.assertEqual((g["proveedores"], g["operativos"]), (D("62"), D("12")))  # solo el flete resta en la ganancia real
        # el mismo documento no se registra dos veces; el doble clic devuelve la misma
        with self.assertRaisesMessage(CompraError, "Ya se registró"):
            registrar_compra(self.jefe, self.prov, self.items(), "FAC", "F001", "45", pago="caja")
        otra = registrar_compra(self.jefe, self.prov, self.items(), "BOL", pago="fuera", token="t1")
        self.assertEqual(registrar_compra(self.jefe, self.prov, self.items(), "BOL", pago="fuera", token="t1"), otra)

    def test_validaciones_no_dejan_nada_a_medias(self):
        with self.assertRaisesMessage(CompraError, "ábrela primero"):
            registrar_compra(self.jefe, self.prov, self.items(), pago="caja")
        with self.assertRaisesMessage(CompraError, "no controla stock"):
            registrar_compra(self.jefe, self.prov, [{"variante": self.plato.pk, "cantidad": "1", "costo": "3"}], pago="fuera")
        with self.assertRaisesMessage(CompraError, "línea libre"):
            registrar_compra(self.jefe, self.prov, [{"variante": None, "descripcion": " ", "cantidad": "1", "costo": "3"}], pago="fuera")
        with self.assertRaisesMessage(CompraError, "futura"):
            registrar_compra(self.jefe, self.prov, self.items(), fecha=self.hoy + timedelta(days=1), pago="fuera")
        with self.assertRaisesMessage(CompraError, "Indica si se pagó"):
            registrar_compra(self.jefe, self.prov, self.items())
        self.assertFalse(Compra.objects.exists())
        self.arroz.refresh_from_db()
        self.assertEqual(self.arroz.stock, D("10"))

    def test_credito_pagos_repartidos_y_anulacion(self):
        c1 = registrar_compra(self.jefe, self.prov, self.items("10", "5"), "FAC", "F001", "1", fecha=self.hoy - timedelta(days=20), credito=True)
        c2 = registrar_compra(self.jefe, self.prov, self.items("5", "6"), "FAC", "F001", "2", credito=True, vence=self.hoy + timedelta(days=3))
        self.assertEqual((c1.vence, c1.estado, c2.estado), (self.hoy - timedelta(days=5), "Vencida", "Por pagar"))
        d = deudas_por_proveedor()[0]
        self.assertEqual((d["deuda"], d["vencido"], d["compras"]), (D("80"), D("50"), 2))
        self.assertEqual(len(vencen_pronto()), 2)
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("core:inicio")), "pago a proveedores vencido")
        with self.assertRaisesMessage(CompraError, "solo se le debe S/ 80.00"):
            pagar_proveedor(self.prov, D("100"), self.jefe, "fuera")
        pagos = pagar_proveedor(self.prov, D("60"), self.jefe, "fuera")  # 50 a la primera, 10 a la segunda
        self.assertEqual([(p.compra, p.monto) for p in pagos], [(c1, D("50")), (c2, D("10"))])
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual((c1.saldo, c2.saldo), (D("0"), D("20")))
        with self.assertRaisesMessage(CompraError, "Solo se debe S/ 20.00"):
            pagar(c2, D("25"), self.jefe, "fuera")
        # anular: primero los pagos fuera de caja; luego sale del stock lo que entró
        with self.assertRaisesMessage(CompraError, "anúlalos primero"):
            anular_compra(c2, self.jefe, "error")
        anular_gasto(pagos[1], self.jefe, "se pagó a otra")
        c2.refresh_from_db()
        self.assertEqual(c2.saldo, D("30"))
        anular_compra(c2, self.jefe, "factura equivocada")
        c2.refresh_from_db()
        self.arroz.refresh_from_db()
        self.assertEqual((c2.estado, c2.saldo, self.arroz.stock), ("Anulada", D("0"), D("20")))
        self.assertTrue(MovimientoStock.objects.filter(tipo="ANC", cantidad=D("-5")).exists())
        self.assertEqual(deudas_por_proveedor(), [])

    def test_pantallas(self):
        self.client.force_login(self.jefe)
        abrir(self.jefe, D("0"))
        r = self.client.get(reverse("compras:nueva"))
        self.assertContains(r, "Arroz 1 kg")
        self.assertNotContains(r, "Lomo")  # sin stock: no se compra como producto
        datos = {"proveedor": self.prov.pk, "documento": "FAC", "serie": "F001", "numero": "9", "fecha": self.hoy.isoformat(),
                 "pago": "credito", "vence": "", "nota": "", "token": "x1", "items": json.dumps(self.items("2", "5", libre="3"))}
        r = self.client.post(reverse("compras:nueva"), datos)
        c = Compra.objects.get()
        self.assertRedirects(r, reverse("compras:detalle", args=[c.pk]))
        self.assertEqual((c.total, c.vence), (D("13"), self.hoy + timedelta(days=15)))
        r = self.client.post(reverse("compras:nueva"), {**datos, "token": "x2"})
        self.assertContains(r, "Ya se registró")
        self.assertContains(self.client.get(reverse("compras:detalle", args=[c.pk])), "Registrar pago")
        self.client.post(reverse("compras:pagar", args=[c.pk]), {"monto": "13", "origen": "caja"})
        self.assertEqual(c.saldo, D("0"))
        for nombre in ("lista", "por_pagar", "proveedores", "proveedor_nuevo"):
            self.assertEqual(self.client.get(reverse(f"compras:{nombre}")).status_code, 200)
        self.assertContains(self.client.get(reverse("compras:lista") + "?estado=pagadas"), "Distribuidora Lima")
        r = self.client.post(reverse("compras:proveedor_nuevo") + "?next=" + reverse("compras:nueva"),
                             {"ruc": "20100070971", "nombre": "X", "plazo": "0", "activo": "on"})
        self.assertContains(r, "RUC válido")
        r = self.client.post(reverse("compras:proveedor_nuevo") + "?next=" + reverse("compras:nueva"),
                             {"ruc": "", "nombre": "Mercado  central", "plazo": "0", "activo": "on"})
        nuevo = Proveedor.objects.get(nombre="Mercado central")
        self.assertRedirects(r, reverse("compras:nueva") + f"?proveedor={nuevo.pk}", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("compras:proveedor", args=[self.prov.pk])), "F001-9")
        self.assertContains(self.client.get(reverse("core:inicio")), "Compras")
        self.client.force_login(self.cajero)  # por defecto, solo Administración
        self.assertEqual(self.client.get(reverse("compras:lista")).status_code, 403)

    def test_todo_funciona_sin_el_modulo(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["compras"])
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(reverse("compras:lista")).status_code, 403)
        r = self.client.get(reverse("core:inicio"))
        self.assertNotContains(r, reverse("compras:lista"))
        # el stock sigue entrando por Productos y el pago a proveedor es un egreso suelto, como siempre
        self.client.post(reverse("productos:movimiento", args=[self.arroz.producto_id]),
                         {"variante": self.arroz.pk, "operacion": "ING", "cantidad": "5", "costo_unitario": "6", "nota": "", "referencia": "F1"})
        self.arroz.refresh_from_db()
        self.assertEqual(self.arroz.stock, D("15"))
        s = abrir(self.jefe, D("50"))
        self.client.post(reverse("caja:egreso", args=[s.pk]), {"categoria": "PRO", "monto": "30", "concepto": "Arroz"})
        self.assertEqual(MovimientoCaja.objects.get().compra, None)
        g = gastos(self.hoy, self.hoy)
        self.assertEqual((g["proveedores"], g["operativos"]), (D("30"), D("0")))
        self.assertEqual(self.client.get(reverse("reportes:inicio")).status_code, 200)


class ConexionesTests(Base):
    """Compras en Reportes y Excel, última compra en el producto y reposición por proveedor."""

    def test_reportes_producto_y_reponer(self):
        from io import BytesIO

        from openpyxl import load_workbook

        self.prov.telefono = "987 654 321"
        self.prov.save()
        registrar_compra(self.jefe, self.prov, self.items("6", "5", libre="4"), "FAC", "F001", "7", credito=True)
        self.arroz.producto.stock_minimo = D("50")  # 16 en stock: queda por reponer
        self.arroz.producto.save()
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("reportes:inicio") + "?p=hoy")
        self.assertContains(r, 'id="compras"')
        self.assertEqual((r.context["compras"]["total"], r.context["compras"]["deuda"]), (D("34"), D("34")))
        libro = load_workbook(BytesIO(self.client.get(reverse("reportes:inicio") + "?p=hoy&excel=1").content))
        self.assertIn("Registro de compras", libro.sheetnames)
        fila = [c.value for c in libro["Registro de compras"][2]]
        self.assertEqual((fila[1], fila[2], fila[3], fila[8], fila[9], fila[12]), ("Factura", "F001", "7", 34, "Crédito", 34))
        self.assertContains(self.client.get(reverse("productos:detalle", args=[self.arroz.producto_id])), "Última compra")
        r = self.client.get(reverse("compras:reponer"))
        self.assertContains(r, "Arroz 1 kg")
        self.assertContains(r, "wa.me/51987654321")
        r = self.client.get(reverse("compras:nueva") + f"?reponer={self.prov.pk}&proveedor={self.prov.pk}")
        self.assertEqual(json.loads(r.context["items_previos"]), [{"variante": self.arroz.pk, "cantidad": "6", "costo": "5"}])
        self.assertContains(self.client.get(reverse("productos:lista")), reverse("compras:reponer"))

    def test_sin_modulo_no_aparece(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["compras"])
        self.client.force_login(self.jefe)
        self.assertNotIn("compras", self.client.get(reverse("reportes:inicio")).context)
        r = self.client.get(reverse("productos:detalle", args=[self.arroz.producto_id]))
        self.assertNotContains(r, "Última compra")
        self.arroz.producto.stock_minimo = D("50")
        self.arroz.producto.save()
        self.assertNotContains(self.client.get(reverse("productos:lista")), reverse("compras:reponer"))
