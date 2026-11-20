import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Ajustes
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock
from ventas.models import Venta
from ventas.servicios import VentaInvalida, anular_venta, registrar_venta

from .models import MovimientoCaja, SesionCaja
from .servicios import CajaError, abrir, calcular, cerrar, movimiento, total_conteo

D = Decimal


class CajaTests(TestCase):
    def setUp(self):
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        p = Producto.objects.create(nombre="Gaseosa", precio=D("2.50"))
        self.v = asegurar_variante_unica(p)
        mover_stock(self.v, 50, MovimientoStock.Tipo.INGRESO)

    def vender(self, usuario, cant, pagos):
        return registrar_venta(usuario, [{"variante": self.v.pk, "cantidad": str(cant)}], pagos)

    def test_sin_caja_no_se_vende(self):
        with self.assertRaisesMessage(VentaInvalida, "Abre tu caja"):
            self.vender(self.cajero, 1, [{"metodo": "EFE", "monto": "2.50"}])
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True})
        self.assertIsNone(self.vender(self.cajero, 1, [{"metodo": "EFE", "monto": "2.50"}]).sesion_caja)

    def test_turno_completo(self):
        s = abrir(self.cajero, D("100"))
        with self.assertRaises(CajaError):
            abrir(self.cajero, D("50"))
        v1 = self.vender(self.cajero, 4, [{"metodo": "EFE", "monto": "20"}])      # 10 en efectivo, vuelto 10
        self.vender(self.cajero, 2, [{"metodo": "YAP", "monto": "5"}])            # 5 por Yape
        v3 = self.vender(self.cajero, 2, [{"metodo": "EFE", "monto": "5"}])
        anular_venta(v3, self.jefe, "error")                                       # con la caja abierta: deja de sumar
        movimiento(s, MovimientoCaja.Tipo.EGRESO, D("30"), "Proveedor", self.cajero, MovimientoCaja.Categoria.PROVEEDOR)
        movimiento(s, MovimientoCaja.Tipo.INGRESO, D("5"), "Sencillo", self.cajero)
        r = calcular(s)
        self.assertEqual(v1.sesion_caja, s)
        self.assertEqual((r["efectivo_ventas"], r["total_ventas"], r["esperado"], r["anuladas"]), (D("10"), D("15"), D("85"), 1))
        s = cerrar(s, D("84"), self.cajero, nota="faltó 1")
        self.assertEqual((s.esperado, s.diferencia, s.estado), (D("85"), D("-1"), "CER"))
        self.assertEqual(D(s.resumen["esperado"]), D("85"))
        with self.assertRaises(CajaError):
            cerrar(s, D("85"), self.cajero)
        # anular una venta de una caja ya cerrada: sin caja abierta no se puede (el efectivo saldría sin rastro)
        with self.assertRaisesMessage(VentaInvalida, "abre tu caja primero"):
            anular_venta(v1, self.jefe, "devolución")
        v1.refresh_from_db()
        self.assertFalse(v1.anulada)
        # con su caja abierta, el efectivo sale de ahí
        s2 = abrir(self.jefe, D("0"))
        anular_venta(v1, self.jefe, "devolución")
        egreso = s2.movimientos.get()
        self.assertEqual((egreso.monto, egreso.automatico, egreso.categoria), (D("10"), True, "DEV"))
        s.refresh_from_db()
        self.assertEqual(s.esperado, D("85"))  # el cierre no cambia

    def test_conteo(self):
        self.assertEqual(total_conteo({"100": "1", "0.50": 3, "7": 5, "20": "x"}), (D("101.50"), {"100": 1, "0.50": 3}))

    def test_vistas(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("caja:mi_caja"))
        self.assertContains(r, "Abrir caja")
        self.client.post(reverse("caja:mi_caja"), {"monto_inicial": "50"})
        s = SesionCaja.abierta_de(self.cajero)
        self.assertEqual(s.monto_inicial, D("50"))
        self.assertRedirects(self.client.get(reverse("caja:mi_caja")), reverse("caja:sesion", args=[s.pk]))
        self.client.post(reverse("caja:egreso", args=[s.pk]), {"categoria": "GAS", "monto": "8", "concepto": "Movilidad"})
        r = self.client.post(reverse("ventas:registrar"), json.dumps({"items": [{"variante": self.v.pk, "cantidad": "2"}], "pagos": [{"metodo": "EFE", "monto": "5"}]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("caja:cerrar", args=[s.pk]))
        self.assertEqual(r.context["r"]["esperado"], D("47"))
        self.assertContains(r, 'id="contado-m"')  # celular: lo contado en la barra fija (sin la diferencia)
        self.client.post(reverse("caja:cerrar", args=[s.pk]), {"contado": "0", "d_20": "2", "d_5": "1", "d_1": "2"})
        s.refresh_from_db()
        self.assertEqual((s.contado, s.diferencia, s.conteo), (D("47"), D("0"), {"20": 2, "5": 1, "1": 2}))
        self.assertEqual(self.client.get(reverse("caja:historial")).status_code, 403)
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("caja:historial")), "Cuadró")
        self.assertEqual(self.client.get(reverse("caja:sesion", args=[s.pk])).status_code, 200)
        otro = User.objects.create_user("otro", password="x-clave-123")
        otro.groups.add(Group.objects.get(name="Vendedor"))
        self.client.force_login(otro)
        self.assertEqual(self.client.get(reverse("caja:sesion", args=[s.pk])).status_code, 403)


class GastosTests(TestCase):
    """Gastos del periodo (de las cajas y fuera de caja), ganancia real y pagos ligados a la persona."""

    def setUp(self):
        from personal.models import Persona

        Ajustes.objects.update_or_create(pk=1, defaults={"funciones_inactivas": []})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.ana = Persona.objects.create(nombre="Ana")
        p = Producto.objects.create(nombre="Gaseosa", precio=D("10"), costo=D("4"))
        self.v = asegurar_variante_unica(p)
        mover_stock(self.v, 50, MovimientoStock.Tipo.INGRESO)

    def test_gastos_y_ganancia_real(self):
        from datetime import timedelta

        from django.utils import timezone

        from .servicios import gasto_fuera_de_caja, gastos

        C, E = MovimientoCaja.Categoria, MovimientoCaja.Tipo.EGRESO
        hoy = timezone.localdate()
        s = abrir(self.cajero, D("100"))
        v = registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "10"}], [{"metodo": "EFE", "monto": "100"}])  # ganancia 60
        movimiento(s, E, D("30"), "Gaseosas", self.cajero, C.PROVEEDOR)
        movimiento(s, E, D("20"), "Movilidad", self.cajero, C.GASTO)
        movimiento(s, E, D("50"), "Adelanto", self.cajero, C.PERSONAL, persona=self.ana)
        movimiento(s, E, D("40"), "Para el banco", self.cajero, C.RETIRO, persona=self.ana)  # retiro: no es gasto ni se liga
        v2 = registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "10"}])
        cerrar(s, D("70"), self.cajero)
        abrir(self.jefe, D("0"))
        anular_venta(v2, self.jefe, "error")  # caja cerrada: devolución automática, no es gasto
        alquiler = gasto_fuera_de_caja(D("300"), "Alquiler", self.jefe, C.GASTO, hoy)
        self.assertIsNone(alquiler.sesion)
        self.assertEqual(MovimientoCaja.objects.filter(persona=self.ana).count(), 1)
        with self.assertRaises(CajaError):
            gasto_fuera_de_caja(D("10"), "Retiro", self.jefe, C.RETIRO)
        with self.assertRaises(CajaError):
            gasto_fuera_de_caja(D("10"), "Mañana", self.jefe, C.GASTO, hoy + timedelta(days=1))

        g = gastos(hoy, hoy)
        self.assertEqual(g["total"], D("400"))          # 30 + 20 + 50 + 300
        self.assertEqual(g["proveedores"], D("30"))
        self.assertEqual(g["operativos"], D("370"))
        self.assertEqual(g["retiros"], D("40"))
        self.assertEqual(g["fuera"], D("300"))
        self.assertEqual([f["etiqueta"] for f in g["filas"]][0], "Gasto del local")
        self.assertEqual(calcular(s)["egresos"], D("140"))  # el gasto fuera de caja no toca la caja

        self.client.force_login(self.jefe)
        r = self.client.get(reverse("reportes:inicio") + "?p=hoy")
        self.assertContains(r, "Ganancia real")
        self.assertEqual(r.context["gastos"]["ganancia_real"], v.total - D("40") - D("370"))  # 60 − 370
        self.assertEqual(self.client.get(reverse("reportes:inicio") + "?p=hoy&excel=1").status_code, 200)
        r = self.client.get(reverse("caja:gastos"))
        self.assertContains(r, "Alquiler")
        self.assertContains(r, "no es gasto")
        r = self.client.post(reverse("caja:gasto_nuevo"), {"dia": hoy.isoformat(), "categoria": C.PERSONAL, "monto": "80", "concepto": "Sueldo"})
        self.assertContains(r, "Elige a quién")
        r = self.client.post(reverse("caja:gasto_nuevo"), {"dia": hoy.isoformat(), "categoria": C.PERSONAL, "persona": self.ana.pk,
                                                           "monto": "80", "concepto": "Sueldo"})
        self.assertRedirects(r, reverse("caja:gastos"))
        self.assertEqual(MovimientoCaja.objects.filter(persona=self.ana).count(), 2)
        self.client.post(reverse("caja:gasto_anular", args=[alquiler.pk]))  # sin motivo no se anula
        alquiler.refresh_from_db()
        self.assertFalse(alquiler.anulado)
        self.client.post(reverse("caja:gasto_anular", args=[alquiler.pk]), {"motivo": "Se registró dos veces"})
        alquiler.refresh_from_db()
        self.assertEqual((alquiler.anulado, alquiler.anulado_por, alquiler.motivo_anulacion), (True, self.jefe, "Se registró dos veces"))
        self.assertEqual(gastos(hoy, hoy)["fuera"], D("80"))  # el alquiler anulado ya no cuenta; el sueldo sí
        self.assertContains(self.client.get(reverse("caja:gastos")), "Anulado")
        m = MovimientoCaja.objects.get(concepto="Movilidad")
        self.client.post(reverse("caja:gasto_anular", args=[m.pk]), {"motivo": "x"})  # los de una caja no se anulan aquí
        self.assertEqual(self.client.post(reverse("caja:gasto_anular", args=[m.pk]), {"motivo": "x"}).status_code, 404)
        m.refresh_from_db()
        self.assertFalse(m.anulado)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("caja:gastos")).status_code, 403)


class CierreCiegoTests(TestCase):
    """Cierre ciego, sencillo que se deja para el siguiente turno y caja que se cierra mientras se cobra."""

    def setUp(self):
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Gaseosa", precio=D("10")))
        mover_stock(self.v, 50, MovimientoStock.Tipo.INGRESO)

    def test_cajero_no_ve_lo_esperado_y_deja_sencillo(self):
        self.client.force_login(self.cajero)
        self.client.post(reverse("caja:mi_caja"), {"monto_inicial": "100"})
        s = SesionCaja.abierta_de(self.cajero)
        registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "3"}], [{"metodo": "EFE", "monto": "30"}])
        for url in (reverse("caja:sesion", args=[s.pk]), reverse("caja:cerrar", args=[s.pk]), reverse("caja:imprimir", args=[s.pk])):
            r = self.client.get(url)
            self.assertNotContains(r, "130.00")  # lo que debe haber no aparece en ninguna parte
            self.assertNotContains(r, "Debe haber")
        self.assertContains(self.client.get(reverse("caja:cerrar", args=[s.pk])), "ESPERADO = null")
        # el supervisor sí lo ve
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("caja:sesion", args=[s.pk])), "Debe haber")
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("caja:cerrar", args=[s.pk]), {"contado": "128", "queda": "200"})
        self.assertContains(r, "No puedes dejar más")
        r = self.client.post(reverse("caja:cerrar", args=[s.pk]), {"contado": "128", "queda": "100"}, follow=True)
        self.assertContains(r, "Contaste S/ 128.00")
        self.assertNotContains(r, "faltante de")
        s.refresh_from_db()
        self.assertEqual((s.diferencia, s.queda, s.retirado), (D("-2"), D("100"), D("28")))
        self.assertContains(r, "Se retiró al cerrar")  # ya cerrada: se ve todo
        # el siguiente turno propone lo que se dejó; si se encuentra otra cosa, queda anotado
        r = self.client.get(reverse("caja:mi_caja"))
        self.assertEqual(r.context["form"].initial["monto_inicial"], D("100"))
        self.client.post(reverse("caja:mi_caja"), {"monto_inicial": "90"})
        self.assertIn("Se dejaron S/ 100.00 y se encontraron S/ 90.00", SesionCaja.abierta_de(self.cajero).nota_apertura)
        from .servicios import gastos
        from django.utils import timezone

        hoy = timezone.localdate()
        self.assertEqual(gastos(hoy, hoy)["retiros"], D("28"))

    def test_cobro_en_una_caja_que_se_acaba_de_cerrar(self):
        s = abrir(self.cajero, D("0"))
        vieja = SesionCaja.objects.get(pk=s.pk)  # lo que tenía en mano quien cobra
        cerrar(s, D("0"), self.jefe)
        from .servicios import bloquear_abierta

        with self.assertRaises(CajaError):
            bloquear_abierta(vieja)
        with self.assertRaises(CajaError):
            movimiento(vieja, MovimientoCaja.Tipo.EGRESO, D("5"), "x", self.cajero)
        from unittest import mock

        with mock.patch("caja.servicios.sesion_para_vender", return_value=vieja):
            with self.assertRaisesMessage(VentaInvalida, "se acaba de cerrar"):
                registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "10"}])
        self.assertFalse(Venta.objects.filter(sesion_caja=vieja).exists())


class CostoPromedioTests(TestCase):
    def test_promedio_ponderado(self):
        from productos.servicios import costo_promedio

        v = asegurar_variante_unica(Producto.objects.create(nombre="Arroz", precio=D("6")))
        mover_stock(v, 10, MovimientoStock.Tipo.INGRESO, costo_unitario=D("5"))
        mover_stock(v, 10, MovimientoStock.Tipo.INGRESO, costo_unitario=D("8"))
        v.refresh_from_db()
        self.assertEqual(v.costo, D("6.50"))
        mover_stock(v, -15, MovimientoStock.Tipo.VENTA)                         # quedan 5 a 6.50
        mover_stock(v, 15, MovimientoStock.Tipo.INGRESO, costo_unitario=D("7"))  # (5×6.50 + 15×7) ÷ 20
        v.refresh_from_db()
        self.assertEqual(v.costo, D("6.88"))
        self.assertEqual(costo_promedio(D("-3"), D("6"), D("10"), D("9")), D("9"))  # stock negativo: manda el nuevo
        self.assertEqual(costo_promedio(D("4"), None, D("10"), D("9")), D("9"))
