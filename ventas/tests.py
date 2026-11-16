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
        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True})
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


class CombosTests(Base):
    def setUp(self):
        super().setUp()
        from productos.models import ComboItem, GrupoOpciones, Opcion

        mover_stock(self.va, 20, MovimientoStock.Tipo.INGRESO)
        self.agua = Producto.objects.create(nombre="Agua", precio=D("2"), costo=D("0.80"))
        self.vagua = asegurar_variante_unica(self.agua)
        mover_stock(self.vagua, 10, MovimientoStock.Tipo.INGRESO)
        self.combo = Producto.objects.create(nombre="Combo", precio=D("12"), tipo="C", maneja_stock=True)
        self.vcombo = asegurar_variante_unica(self.combo)
        ComboItem.objects.create(combo=self.combo, variante=self.va, cantidad=D("2"))
        g = GrupoOpciones.objects.create(nombre="Combo: Bebida", minimo=1, maximo=1)
        self.op_gas = Opcion.objects.create(grupo=g, nombre="Gaseosa", variante=self.vg, por_defecto=True, orden=0)
        self.op_agua = Opcion.objects.create(grupo=g, nombre="Agua", variante=self.vagua, orden=1)
        self.combo.grupos.add(g)

    def test_vender_y_anular_combo(self):
        from productos.models import Variante

        self.combo.refresh_from_db()
        self.assertFalse(self.combo.maneja_stock)  # el combo no tiene stock propio
        venta = registrar_venta(self.admin, [{"variante": self.vcombo.pk, "cantidad": "3", "opciones": [self.op_agua.pk]}],
                                [{"metodo": "EFE", "monto": "36"}])
        stock = lambda v: Variante.objects.get(pk=v.pk).stock
        self.assertEqual((stock(self.va), stock(self.vagua), stock(self.vg)), (D("14"), D("7"), D("10")))  # 2 kg × 3 y 1 agua × 3
        item = venta.items.get()
        self.assertEqual(item.descripcion, "Combo (Agua)")  # el ticket no lista lo que trae
        self.assertEqual(item.costo_unitario, None)  # el arroz no tiene costo: no se inventa
        anular_venta(venta, self.admin, "prueba")
        self.assertEqual((stock(self.va), stock(self.vagua)), (D("20"), D("10")))

    def test_sin_elegir_va_lo_incluido_y_costo(self):
        from productos.models import Variante

        self.arroz.costo = D("3")
        self.arroz.save()
        venta = registrar_venta(self.admin, [{"variante": self.vcombo.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "12"}])
        self.assertEqual(Variante.objects.get(pk=self.vg.pk).stock, D("9"))  # la gaseosa viene incluida
        self.assertEqual(venta.items.get().costo_unitario, D("6.00"))  # 2 kg × 3.00

    def test_armar_combo_desde_la_pantalla(self):
        from productos.models import ComboItem

        self.client.force_login(self.admin)
        url = reverse("productos:combo", args=[self.combo.pk])
        self.client.post(url, {"accion": "agregar", "variante": self.vg.pk, "cantidad": "1"})
        self.assertTrue(ComboItem.objects.filter(combo=self.combo, variante=self.vg).exists())
        self.client.post(url, {"accion": "parte", "nombre": "Postre", "variantes": [self.vg.pk, self.vagua.pk]})
        self.assertTrue(self.combo.grupos.filter(nombre="Combo: Postre", opciones__variante=self.vagua).exists())
        r = self.client.get(reverse("productos:detalle", args=[self.combo.pk]))
        self.assertContains(r, "Qué trae el combo")
        self.assertContains(r, "Por separado")
        # un combo no puede traer otro combo
        self.client.post(url, {"accion": "agregar", "variante": self.vcombo.pk, "cantidad": "1"})
        self.assertFalse(ComboItem.objects.filter(combo=self.combo, variante=self.vcombo).exists())


class ReglasCobroTests(Base):
    def test_metodos_descuentos_y_propina(self):
        from core.models import Ajustes

        Ajustes.objects.filter(pk=1).update(metodos_pago=["EFE", "YAP"], descuentos_activos=False)
        item = [{"variante": self.vg.pk, "cantidad": "1"}]
        with self.assertRaisesMessage(VentaInvalida, "no acepta pagos con Tarjeta"):
            registrar_venta(self.admin, item, [{"metodo": "TAR", "monto": "2.50"}])
        with self.assertRaisesMessage(VentaInvalida, "descuentos están desactivados"):
            registrar_venta(self.admin, item, [{"metodo": "EFE", "monto": "2.50"}], descuento="0.50", puede_descontar=True)
        self.assertEqual(registrar_venta(self.admin, item, [{"metodo": "YAP", "monto": "2.50"}]).total, D("2.50"))
        # El cobro solo muestra los métodos aceptados
        self.client.force_login(self.admin)
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, '"id": "YAP"')
        self.assertNotContains(r, '"id": "TAR"')
        self.assertNotContains(r, 'id="descuento"')
        # Al guardar Datos del negocio, el efectivo siempre queda
        a = Ajustes.cargar()
        from core.forms import DatosNegocioForm

        f = DatosNegocioForm({"rubro": a.rubro, "nombre": "X", "color": "#0d6efd", "ticket_ancho": 80, "nivel_pedido": 2,
                              "delivery_costo": "0", "metodos": ["PLI"]}, instance=a)
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertEqual(Ajustes.cargar().metodos_aceptados, ["EFE", "PLI"])


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
