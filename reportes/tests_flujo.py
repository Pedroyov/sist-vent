"""Dinero del día: entradas, salidas, retiros, lo que quedó y diferencias, día por día."""
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from caja.models import MovimientoCaja
from caja.servicios import abrir, cerrar, gasto_fuera_de_caja, gastos, movimiento
from clientes.models import Cliente
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock
from ventas.conciliacion import conciliar
from ventas.servicios import registrar_venta

from .flujo import por_dia

D = Decimal


class DineroDelDiaTests(TestCase):
    def test_un_dia_completo(self):
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        v = asegurar_variante_unica(Producto.objects.create(nombre="Menú", precio=D("5")))
        mover_stock(v, 100, MovimientoStock.Tipo.INGRESO)
        rosa = Cliente.objects.create(nombre="Rosa", limite_credito=D("100"))
        hoy = timezone.localdate()
        s = abrir(jefe, D("100"))
        registrar_venta(jefe, [{"variante": v.pk, "cantidad": "6"}], [{"metodo": "EFE", "monto": "50"}])  # paga con 50: vuelto 20
        registrar_venta(jefe, [{"variante": v.pk, "cantidad": "2"}], [{"metodo": "YAP", "monto": "10"}])
        registrar_venta(jefe, [{"variante": v.pk, "cantidad": "1"}], [{"metodo": "CRE", "monto": "5"}], cliente_id=rosa.pk, puede_fiar=True)
        movimiento(s, MovimientoCaja.Tipo.EGRESO, D("8"), "Bolsas", jefe, MovimientoCaja.Categoria.GASTO)
        gasto_fuera_de_caja(D("20"), "Luz", jefe, MovimientoCaja.Categoria.GASTO)
        cerrar(s, D("122"), jefe, queda=D("100"))  # 100 + 30 − 8 = 122; se lleva 22
        conciliar(hoy, "YAP", "10", jefe)

        d = por_dia(hoy, hoy)
        f = d["filas"][0]
        self.assertEqual((f["efectivo"], f["electronico"], f["entro"]), (D("30.00"), D("10.00"), D("40.00")))
        self.assertEqual((f["salio_cajas"], f["salio_fuera"], f["salio"], f["neto"]), (D("8.00"), D("20.00"), D("28.00"), D("12.00")))
        self.assertEqual((f["retirado"], f["quedo"], f["dif_caja"], f["fiado"]), (D("22.00"), D("100.00"), D("0.00"), D("5.00")))
        self.assertEqual(f["sin_conciliar"], [])
        self.assertEqual(gastos(hoy, hoy)["retiros"], D("22.00"))  # la misma definición de retiros

        self.client.force_login(jefe)
        r = self.client.get(reverse("reportes:dinero"))
        self.assertContains(r, "Dinero del día")
        self.assertContains(r, "Vendido al fiado")
        self.assertContains(self.client.get(reverse("reportes:inicio")), reverse("reportes:dinero"))
        r = self.client.get(reverse("reportes:dinero"), {"excel": "1"})
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws.cell(row=1, column=1).value, "Día")
        self.assertEqual(ws.cell(row=ws.max_row, column=1).value, "Total")
