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

from .conectores import ErrorConexion, Nubefact, Resultado
from .models import Comprobante, Config


class FacturacionTests(TestCase):
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
        # factura al fiado: aún no
        r = self._vender({"tipo": "F", "doc": ruc, "nombre": "ACME SAC", "direccion": "Av. Lima 1"}, pagos=[{"metodo": "CRE", "monto": "61"}],
                         cliente_nombre="ACME", cliente_documento=ruc)
        self.assertContains(r, "fiado", status_code=400)

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
        self.assertFalse(Comprobante.objects.exists())  # apagado: siempre nota de venta
        self.assertNotContains(self.client.get(reverse("ventas:pos")), 'id="c-comp"')
