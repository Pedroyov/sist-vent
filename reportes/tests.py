from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from caja.servicios import abrir, cerrar
from core.models import Ajustes
from mesas.models import Mesa, Zona
from mesas.servicios import abrir_cuenta, agregar, cobrar, enviar_cocina, quitar
from productos.models import Categoria, MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock
from ventas.models import Venta
from ventas.servicios import anular_venta, registrar_venta

from . import servicios as s

D = Decimal


class ReportesTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "propina_activa": True})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123", first_name="Jefa")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.mozo = User.objects.create_user("mozo", password="x-clave-123", first_name="Ana")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.caja = abrir(self.jefe, D("100"))
        bebidas = Categoria.objects.create(nombre="Bebidas")
        platos = Categoria.objects.create(nombre="Platos")
        self.gas = asegurar_variante_unica(Producto.objects.create(nombre="Gaseosa", precio=D("3"), costo=D("2"), categoria=bebidas))
        mover_stock(self.gas, 50, MovimientoStock.Tipo.INGRESO)
        self.lomo = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("20"), costo=D("9"), categoria=platos, maneja_stock=False))
        Producto.objects.create(nombre="Galleta olvidada", precio=D("1"))
        self.hoy = timezone.localdate()

    def vender(self, items, pagos):
        return registrar_venta(self.jefe, [{"variante": v.pk, "cantidad": str(n)} for v, n in items], pagos)

    def test_resumen_y_productos(self):
        self.vender([(self.gas, 2), (self.lomo, 1)], [{"metodo": "EFE", "monto": "26"}])
        self.vender([(self.gas, 4)], [{"metodo": "YAP", "monto": "12"}])
        v = self.vender([(self.lomo, 1)], [{"metodo": "EFE", "monto": "20"}])
        anular_venta(v, self.jefe, "error")
        viejo = self.vender([(self.gas, 1)], [{"metodo": "EFE", "monto": "3"}])  # periodo anterior
        Venta.objects.filter(pk=viejo.pk).update(fecha=timezone.now() - timedelta(days=1))
        r = s.resumen(self.hoy, self.hoy)
        self.assertEqual((r["total"], r["n"], r["anuladas"], r["anuladas_monto"]), (D("38"), 2, 1, D("20")))
        self.assertEqual(r["anterior"]["total"], D("3"))
        self.assertEqual(r["variacion"], D("1166.7"))
        self.assertEqual(r["ganancia"], D("38") - D("12") - D("9"))
        p = s.productos(self.hoy, self.hoy)
        self.assertEqual([(x["nombre"], x["cantidad"], x["total"], x["ganancia"]) for x in p],
                         [("Lomo", D("1"), D("20"), D("11")), ("Gaseosa", D("6"), D("18"), D("6"))])
        self.assertEqual([c["etiqueta"] for c in s.categorias(self.hoy, self.hoy)], ["Platos", "Bebidas"])
        self.assertEqual([x.nombre for x in s.sin_ventas(self.hoy, self.hoy)], ["Galleta olvidada"])
        fechas, mensual = s.por_fecha(self.hoy - timedelta(days=6), self.hoy)
        self.assertEqual((len(fechas), mensual, fechas[-1]["total"], fechas[-2]["total"]), (7, False, D("38"), D("3")))
        self.assertEqual(sum(h["n"] for h in s.por_hora(self.hoy, self.hoy)), 2)
        self.assertEqual(sum(d["total"] for d in s.por_dia_semana(self.hoy, self.hoy)), D("38"))
        meses, mensual = s.por_fecha(self.hoy - timedelta(days=200), self.hoy)
        self.assertTrue(mensual)
        self.assertEqual(sum(m["total"] for m in meses), D("41"))

    def test_mesas_mozos_y_quitados(self):
        mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        c = abrir_cuenta(self.mozo, mesa, 3)
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 3}, {"variante": self.gas.pk, "cantidad": 1}], self.mozo)
        enviar_cocina(c)
        quitar(c.items.get(variante=self.gas), self.jefe, "se cayó", puede_anular=True)
        cobrar(c, self.jefe, [{"metodo": "EFE", "monto": "70"}], propina="6")
        m = s.mesas(self.hoy, self.hoy)
        self.assertEqual((m["atenciones"], m["personas"], m["por_persona"], len(m["quitados"]), m["quitados_valor"]),
                         (1, 3, D("20"), 1, D("3")))
        mozos = s.por_usuario(self.hoy, self.hoy, "atendio")
        self.assertEqual((mozos[0]["etiqueta"], mozos[0]["total"], mozos[0]["propinas"]), ("Ana", D("60"), D("6")))

    def test_inventario_cajas_y_deudores(self):
        from clientes.models import Cliente

        mover_stock(self.gas, -5, MovimientoStock.Tipo.SALIDA, self.jefe, "vencidas")
        cl = Cliente.objects.create(nombre="Rosa", tipo_documento="SD")
        registrar_venta(self.jefe, [{"variante": self.lomo.pk, "cantidad": "1"}], [{"metodo": "CRE", "monto": "20"}],
                        cliente_id=cl.pk, puede_fiar=True)
        cerrar(self.caja, D("95"), self.jefe)
        inv = s.inventario(self.hoy, self.hoy)
        self.assertEqual((inv["valor"], inv["merma"], len(inv["salidas"])), (D("90"), D("10"), 1))
        cj = s.cajas(self.hoy, self.hoy)
        self.assertEqual((cj["n"], cj["faltante"]), (1, D("-5")))
        d = s.deudores()
        self.assertEqual((d["total"], d["filas"][0]["cliente"], d["filas"][0]["dias"]), (D("20"), cl, 0))

    def test_periodos(self):
        rf = RequestFactory()
        self.assertEqual(s.periodo(rf.get("/", {"p": "hoy"}))[:2], (self.hoy, self.hoy))
        d, h, _ = s.periodo(rf.get("/", {"p": "mes_pasado"}))
        self.assertEqual((d.day, (h + timedelta(days=1)).day), (1, 1))
        self.assertEqual(s.periodo(rf.get("/", {"desde": "2026-03-10", "hasta": "2026-03-01"}))[:2],
                         (timezone.datetime(2026, 3, 1).date(), timezone.datetime(2026, 3, 10).date()))
        self.assertEqual(s.periodo(rf.get("/", {"desde": "malo"}))[2], "7d")

    def test_vistas_y_permisos(self):
        self.vender([(self.gas, 2)], [{"metodo": "EFE", "monto": "6"}])
        self.client.force_login(self.mozo)
        self.assertEqual(self.client.get(reverse("reportes:inicio")).status_code, 403)
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("reportes:inicio") + "?p=hoy")
        self.assertContains(r, "Lo más vendido")
        self.assertContains(r, "Por mozo")       # restaurante: mesas activas
        self.assertContains(r, "Deudores")       # clientes activo
        r = self.client.get(reverse("reportes:inicio") + "?p=30d&excel=1")
        hojas = load_workbook(BytesIO(r.content)).sheetnames
        self.assertIn("Productos", hojas)
        self.assertIn("Platos quitados", hojas)
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["mesas", "clientes"])
        r = self.client.get(reverse("reportes:inicio"))
        self.assertNotContains(r, "Por mozo")
        self.assertNotContains(r, "Deudores (fiado)")
