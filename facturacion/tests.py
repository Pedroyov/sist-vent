import json
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica
from ventas.models import Venta

from .conectores import ErrorConexion, Nubefact, Resultado
from .models import Comprobante, Config


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "ruc": "20123456789", "razon_social": "MI NEGOCIO SAC"})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        abrir(self.cajero, D("0"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Lomo saltado", precio=D("28"), maneja_stock=False))
        self.s = asegurar_variante_unica(Producto.objects.create(nombre="Envío", precio=D("5"), maneja_stock=False, tipo="S", unidad="SRV"))
        self.client.force_login(self.cajero)

    def _vender(self, comprobante=None, **extra):
        datos = {"items": [{"variante": self.v.pk, "cantidad": "2"}, {"variante": self.s.pk, "cantidad": "1"}],
                 "pagos": [{"metodo": "EFE", "monto": "100"}], "comprobante": comprobante, **extra}
        return self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")


class FacturacionTests(Base):
    def test_boleta_simple_con_igv(self):
        r = self._vender({"tipo": "B"})
        self.assertEqual(r.status_code, 200, r.content)
        c = Comprobante.objects.get()
        self.assertEqual((c.numero_str, c.tipo, c.cliente_tipo_doc, c.estado), ("B001-00000001", "03", "-", "ACE"))
        # 61.00 con IGV, calculado por línea como lo valida SUNAT: 56.00 -> 47.46 + 8.54 ; 5.00 -> 4.24 + 0.76
        self.assertEqual((c.total, c.gravada, c.igv), (D("61.00"), D("51.70"), D("9.30")))
        self.assertEqual([i["unidad"] for i in c.detalle], ["NIU", "ZZ"])
        self.assertEqual(sum(D(i["total"]) for i in c.detalle), c.total)
        r = self.client.get(reverse("ventas:imprimir", args=[c.venta_id]))
        self.assertContains(r, "BOLETA DE VENTA ELECTRÓNICA")
        self.assertContains(r, "B001-00000001")
        self.assertContains(r, "<svg")  # QR
        self.assertContains(r, "SIN VALOR TRIBUTARIO")  # modo prueba
        self._vender({"tipo": "B"})
        self.assertEqual(Comprobante.objects.latest("id").numero, 2)  # correlativo

    def test_factura_valida_ruc_y_datos(self):
        from clientes.documentos import ruc_valido

        ruc = next(f"2060123456{d}" for d in range(10) if ruc_valido(f"2060123456{d}"))
        for malo, error in [({"tipo": "F", "doc": "123"}, "RUC"), ({"tipo": "F", "doc": ruc}, "social"),
                            ({"tipo": "F", "doc": ruc, "nombre": "ACME SAC"}, "fiscal")]:
            r = self._vender(malo)
            self.assertContains(r, error, status_code=400)
        from ventas.models import Venta

        self.assertFalse(Venta.objects.exists())  # si el comprobante no sale, la venta no se registra
        r = self._vender({"tipo": "F", "doc": ruc, "nombre": "ACME SAC", "direccion": "Av. Lima 1"})
        self.assertEqual(r.status_code, 200)
        c = Comprobante.objects.get()
        self.assertEqual((c.serie, c.cliente_tipo_doc, c.cliente_doc), ("F001", "6", ruc))
        # factura al fiado (crédito): apagada por defecto
        r = self._vender({"tipo": "F", "doc": ruc, "nombre": "ACME SAC", "direccion": "Av. Lima 1"}, pagos=[{"metodo": "CRE", "monto": "61"}],
                         cliente_nombre="ACME", cliente_documento=ruc)
        self.assertContains(r, "activada", status_code=400)

    def test_boleta_mayor_a_700_pide_dni_y_descuento_se_reparte(self):
        datos = {"items": [{"variante": self.v.pk, "cantidad": "30"}], "pagos": [{"metodo": "TAR", "monto": "840"}], "comprobante": {"tipo": "B"}}
        r = self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")
        self.assertContains(r, "DNI", status_code=400)
        self.client.force_login(self.jefe)
        abrir(self.jefe, D("0"))
        datos = {"items": [{"variante": self.v.pk, "cantidad": "1"}, {"variante": self.s.pk, "cantidad": "1"}], "descuento": "3",
                 "pagos": [{"metodo": "EFE", "monto": "30"}], "comprobante": {"tipo": "B", "doc": "45123678", "nombre": "María"}}
        r = self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        c = Comprobante.objects.get()
        self.assertEqual((c.total, c.cliente_tipo_doc), (D("30.00"), "1"))
        self.assertEqual(sum(D(i["total"]) for i in c.detalle), D("30.00"))

    def test_anular_emite_nota_de_credito(self):
        from ventas.servicios import anular_venta

        self._vender({"tipo": "B"})
        c = Comprobante.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            anular_venta(c.venta, self.jefe, "Error al cobrar")
        nc = Comprobante.objects.get(tipo="07")
        self.assertEqual((nc.serie, nc.modifica, nc.total, nc.estado), ("BC01", c, c.total, "ACE"))
        self.assertTrue(c.anulado)
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("ventas:imprimir", args=[c.venta_id])), "NOTA DE CRÉDITO BC01-00000001")

    def test_sin_internet_queda_pendiente_y_se_reenvia(self):
        Config.objects.update_or_create(pk=1, defaults={"proveedor": "NUB", "ruta": "https://api.ejemplo.pe/x", "token": "t"})
        with mock.patch.object(Nubefact, "_post", side_effect=ErrorConexion("sin internet")):
            r = self._vender({"tipo": "B"})
        self.assertEqual(r.status_code, 200)  # la venta se hace igual
        c = Comprobante.objects.get()
        self.assertEqual((c.estado, c.intentos), ("PEN", 1))
        respuesta = {"aceptada_por_sunat": True, "sunat_description": "La Boleta numero B001-1, ha sido aceptada", "enlace_del_pdf": "https://x/pdf",
                     "codigo_hash": "abc123", "cadena_para_codigo_qr": "20123456789|03|B001|1|"}
        with mock.patch.object(Nubefact, "_post", return_value=respuesta) as post:
            self.client.post(reverse("facturacion:reenviar"))
            enviado = post.call_args[0][0]
        c.refresh_from_db()
        self.assertEqual((c.estado, c.enlace_pdf, c.hash), ("ACE", "https://x/pdf", "abc123"))
        self.assertEqual((enviado["tipo_de_comprobante"], enviado["serie"], enviado["numero"], enviado["total"]), (2, "B001", 1, "61.00"))
        self.assertEqual(enviado["items"][0]["tipo_de_igv"], 1)

    def test_nubefact_rechazo_y_ya_existente(self):
        Config.objects.update_or_create(pk=1, defaults={"proveedor": "NUB", "ruta": "https://api.ejemplo.pe/x", "token": "t"})
        with mock.patch.object(Nubefact, "_post", return_value={"errors": "El RUC del cliente no existe", "codigo": 20}):
            self._vender({"tipo": "B"})
        self.assertEqual(Comprobante.objects.get().estado, "REC")
        respuestas = [{"errors": "Este documento ya existe en NubeFacT", "codigo": 23}, {"aceptada_por_sunat": False}]
        with mock.patch.object(Nubefact, "_post", side_effect=respuestas):
            self._vender({"tipo": "B"})
        self.assertEqual(Comprobante.objects.latest("id").estado, "ENV")  # se consultó: enviado, SUNAT confirma luego

    def test_emitir_despues_y_pantallas(self):
        r = self._vender(None)  # nota de venta
        from ventas.models import Venta

        v = Venta.objects.get()
        self.assertFalse(Comprobante.objects.exists())
        self.assertContains(self.client.get(reverse("ventas:ticket", args=[v.pk])), "Se cobró con nota de venta")
        self.client.post(reverse("facturacion:emitir_venta", args=[v.pk]), {"tipo": "B", "doc": "45123678", "nombre": "María"})
        self.assertEqual(Comprobante.objects.get().cliente_doc, "45123678")
        self.client.post(reverse("facturacion:emitir_venta", args=[v.pk]), {"tipo": "B"})
        self.assertEqual(Comprobante.objects.count(), 1)  # no dos veces
        self.assertContains(self.client.get(reverse("facturacion:lista")), "B001-00000001")
        self.assertEqual(self.client.get(reverse("facturacion:configurar")).status_code, 403)
        self.client.force_login(self.jefe)
        r = self.client.post(reverse("facturacion:configurar"), {"proveedor": "NUB", "igv": "18", "afectacion": "G", "por_defecto": "B",
                                                                 "serie_boleta": "B002", "serie_factura": "F001", "serie_nc_boleta": "BC01",
                                                                 "serie_nc_factura": "FC01"})
        self.assertContains(r, "ruta y el token")

    def test_modulo_apagado(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["facturacion"])
        r = self._vender({"tipo": "B"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Comprobante.objects.exists())  # apagado: siempre nota de venta; la boleta se hace aparte
        self.assertEqual(Venta.objects.latest("id").pide_comprobante, "B")
        self.assertContains(self.client.get(reverse("ventas:pos")), 'data-aparte="1"')


class SeriePorCajaTests(TestCase):
    def setUp(self):
        from caja.models import PuntoCaja

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "ruc": "20123456789", "razon_social": "MI NEGOCIO SAC"})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.barman = User.objects.create_user("barman", password="x-clave-123")
        self.barman.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.caja1 = PuntoCaja.objects.create(nombre="Caja 1")  # sin series propias: usa las generales
        self.barra = PuntoCaja.objects.create(nombre="Barra", serie_boleta="B002", serie_nc_boleta="BC02")
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Pisco sour", precio=D("18"), maneja_stock=False))

    def _vender(self, usuario):
        self.client.force_login(usuario)
        datos = {"items": [{"variante": self.v.pk, "cantidad": "1"}], "pagos": [{"metodo": "EFE", "monto": "18"}], "comprobante": {"tipo": "B"}}
        r = self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        return Comprobante.objects.latest("id")

    def test_cada_caja_con_su_serie(self):
        from caja.servicios import CajaError
        from ventas.servicios import anular_venta

        with self.assertRaises(CajaError):  # con varias cajas hay que elegir una
            abrir(self.cajero, D("0"))
        abrir(self.cajero, D("0"), punto=self.caja1)
        abrir(self.barman, D("0"), punto=self.barra)
        self.assertEqual(self._vender(self.cajero).numero_str, "B001-00000001")
        b = self._vender(self.barman)
        self.assertEqual(b.numero_str, "B002-00000001")
        self.assertEqual(self._vender(self.barman).numero_str, "B002-00000002")
        anular_venta(b.venta, self.jefe, "prueba")
        nc = Comprobante.objects.get(tipo=Comprobante.Tipo.NOTA_CREDITO)
        self.assertEqual(nc.serie, "BC02")  # la nota de crédito usa la serie de la caja de la venta

    def test_pantallas(self):
        self.client.force_login(self.jefe)
        r = self.client.post(reverse("caja:puntos"), {"nombre": "Segundo piso", "serie_boleta": "b003", "activo": "on"})
        self.assertRedirects(r, reverse("caja:puntos"))
        from caja.models import PuntoCaja

        self.assertEqual(PuntoCaja.objects.get(nombre="Segundo piso").serie_boleta, "B003")
        r = self.client.post(reverse("caja:puntos"), {"nombre": "Mala", "serie_boleta": "F001"})
        self.assertContains(r, "empiezan con B")
        self.assertContains(self.client.get(reverse("caja:puntos")), "B002")
        # el cajero elige su caja al abrir
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("caja:mi_caja"))
        self.assertContains(r, "¿En qué caja estás?")
        self.client.post(reverse("caja:mi_caja"), {"monto_inicial": "50", "punto": self.barra.pk})
        from caja.models import SesionCaja

        self.assertEqual(SesionCaja.objects.get(usuario=self.cajero).punto, self.barra)
        self.assertEqual(self.client.get(reverse("caja:puntos")).status_code, 403)  # el cajero no configura


class FacturaCreditoTests(TestCase):
    def setUp(self):
        from clientes.documentos import ruc_valido
        from clientes.models import Cliente

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "ruc": "20123456789", "razon_social": "MI NEGOCIO SAC"})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        abrir(self.cajero, D("0"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Almuerzo", precio=D("100"), maneja_stock=False))
        self.ruc = next(f"2060123456{d}" for d in range(10) if ruc_valido(f"2060123456{d}"))
        self.cli = Cliente.objects.create(tipo_documento="RUC", numero_documento=self.ruc, nombre="ACME SAC", direccion="Av. Lima 1")
        self.client.force_login(self.cajero)

    def _vender(self, pagos, vence=None, cuotas=1):
        comp = {"tipo": "F", "doc": self.ruc, "nombre": "ACME SAC", "direccion": "Av. Lima 1", "cuotas": cuotas}
        if vence:
            comp["vence"] = vence.isoformat()
        datos = {"items": [{"variante": self.v.pk, "cantidad": "1"}], "pagos": pagos, "comprobante": comp, "cliente_id": self.cli.pk}
        return self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")

    def test_apagada_por_defecto(self):
        r = self._vender([{"metodo": "CRE", "monto": "100"}])
        self.assertContains(r, "activada", status_code=400)

    def test_factura_al_credito_y_cuenta_corriente(self):
        from datetime import timedelta

        from django.utils import timezone

        from clientes.servicios import ClienteError, deudas, marcar_incobrable, registrar_abono, validar_fiado

        Config.objects.update_or_create(pk=1, defaults={"credito_activo": True, "credito_dias": 30})
        hoy = timezone.localdate()
        self.assertContains(self._vender([{"metodo": "CRE", "monto": "100"}], vence=hoy), "posterior a hoy", status_code=400)
        r = self._vender([{"metodo": "EFE", "monto": "40"}, {"metodo": "CRE", "monto": "60"}], vence=hoy + timedelta(days=15), cuotas=2)
        self.assertEqual(r.status_code, 200, r.content)
        c = Comprobante.objects.get()
        self.assertEqual((c.forma_pago, c.pendiente, len(c.cuotas)), ("CRE", D("60.00"), 2))
        self.assertEqual([q["monto"] for q in c.cuotas], ["30.00", "30.00"])
        self.assertEqual(c.cuotas[1]["fecha"], (hoy + timedelta(days=45)).isoformat())
        d = Nubefact(Config.cargar(), "20123456789").armar(c)
        self.assertEqual(d["venta_al_credito"][0]["importe"], "30.00")
        self.assertContains(self.client.get(reverse("ventas:imprimir", args=[c.venta_id])), "FORMA DE PAGO: CRÉDITO")
        # cuenta corriente: nada vencido todavía
        filas = deudas(self.cli)
        self.assertEqual((filas[0]["pendiente"], filas[0]["vencido"]), (D("60.00"), D("0")))
        # pasan 20 días: vence la primera cuota; paga 10 → quedan 20 vencidos y no se le fía más sin permiso
        luego = hoy + timedelta(days=20)
        self.assertEqual(deudas(self.cli, hoy=luego)[0]["vencido"], D("30.00"))
        registrar_abono(self.cli, D("10"), "EFE", self.cajero)
        self.assertEqual(deudas(self.cli, hoy=luego)[0]["vencido"], D("20.00"))
        with mock.patch("clientes.servicios.timezone.localdate", return_value=luego):
            with self.assertRaisesMessage(ClienteError, "vencido"):
                validar_fiado(self.cli, D("5"), True, False)
            validar_fiado(self.cli, D("5"), True, True)  # con permiso (o un supervisor) sí
        # el negocio da por perdido el resto
        marcar_incobrable(self.cli, D("50"), "La empresa cerró", self.jefe)
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.saldo, D("0.00"))
        self.assertEqual(deudas(self.cli)[0]["pendiente"], D("0.00"))
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("clientes:detalle", args=[self.cli.pk]))
        self.assertContains(r, "Incobrable")

    def test_excel_para_el_contador(self):
        from io import BytesIO

        from openpyxl import load_workbook

        Config.objects.update_or_create(pk=1, defaults={"credito_activo": True})
        self._vender([{"metodo": "CRE", "monto": "100"}])
        r = self.client.get(reverse("facturacion:excel"))
        self.assertEqual(r.status_code, 200)
        ws = load_workbook(BytesIO(r.content))["Registro de ventas"]
        fila = [c.value for c in ws[2]]
        self.assertEqual((fila[1], fila[11], fila[12], fila[14]), ("Factura electrónica", 100, "Crédito", 100))


class ReenvioAutomaticoTests(Base):
    """Lo que SUNAT aún no recibe se reintenta solo y avisa antes de que venza el plazo."""

    def test_reenvio_y_aviso(self):
        from datetime import timedelta
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        from .servicios import vence_envio

        Config.objects.update_or_create(pk=1, defaults={"proveedor": "NUB", "ruta": "https://api.ejemplo.pe/x", "token": "t"})
        with mock.patch.object(Nubefact, "_post", side_effect=ErrorConexion("sin internet")):
            self._vender({"tipo": "B"}, token="a")
            self._vender({"tipo": "B"}, token="b")
        primero, segundo = Comprobante.objects.order_by("id")
        hace_dos_dias = timezone.now() - timedelta(days=2)
        Comprobante.objects.filter(pk=primero.pk).update(creado=hace_dos_dias, fecha=hace_dos_dias.date())
        primero.refresh_from_db()
        self.assertEqual(vence_envio(primero), primero.fecha + timedelta(days=3))
        # aviso en el inicio para quien ve comprobantes (solo el atrasado: el otro se acaba de emitir)
        r = self.client.get(reverse("core:inicio"))
        self.assertContains(r, "1 comprobante sin aceptar por SUNAT")
        # la tarea programada: sin internet falla (sale con error para que alguien lo revise)
        with mock.patch.object(Nubefact, "_post", side_effect=ErrorConexion("sin internet")):
            with self.assertRaises(SystemExit):
                call_command("reenviar_comprobantes", stdout=StringIO(), stderr=StringIO())
        # con internet: la siguiente venta se envía y de paso se reenvían los atrasados
        respuesta = {"aceptada_por_sunat": True, "sunat_description": "Aceptada", "codigo_hash": "h"}
        with mock.patch.object(Nubefact, "_post", return_value=respuesta):
            self._vender({"tipo": "B"}, token="c")
        self.assertFalse(Comprobante.objects.filter(estado__in=["PEN", "ENV"]).exists())
        salida = StringIO()
        call_command("reenviar_comprobantes", stdout=salida, stderr=StringIO())
        self.assertIn("Reenviados: 0", salida.getvalue())
        self.assertNotContains(self.client.get(reverse("core:inicio")), "sin aceptar por SUNAT")
