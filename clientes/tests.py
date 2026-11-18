import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.servicios import abrir, calcular, cerrar
from productos.models import Producto
from productos.servicios import asegurar_variante_unica
from ventas.servicios import VentaInvalida, anular_venta, registrar_venta

from .documentos import ruc_valido, validar
from .models import Cliente
from .servicios import ClienteError, anular_abono, registrar_abono, total_por_cobrar

D = Decimal


class DocumentosTests(TestCase):
    def test_validacion(self):
        self.assertTrue(ruc_valido("20100047218"))   # RUC real de ejemplo (BCP)
        self.assertFalse(ruc_valido("20100047219"))
        self.assertFalse(ruc_valido("30100047218"))
        self.assertEqual(validar("DNI", " 4512 3678 "), ("45123678", None))
        self.assertIsNotNone(validar("DNI", "1234567")[1])
        self.assertEqual(validar("SD", "lo que sea"), ("", None))


class FiadoTests(TestCase):
    def setUp(self):
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.vendedor = User.objects.create_user("vendedor", password="x-clave-123")
        self.vendedor.groups.add(Group.objects.get(name="Vendedor"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        for u in (self.cajero, self.vendedor, self.jefe):
            abrir(u, D("100"))
        p = Producto.objects.create(nombre="Arroz", precio=D("10"), maneja_stock=False)
        self.v = asegurar_variante_unica(p)
        self.maria = Cliente.objects.create(tipo_documento="DNI", numero_documento="45123678", nombre="María", limite_credito=D("50"))

    def vender(self, usuario, cant, pagos, **kw):
        kw.setdefault("puede_fiar", True)
        return registrar_venta(usuario, [{"variante": self.v.pk, "cantidad": str(cant)}], pagos, **kw)

    def test_fiado_limite_y_pagos(self):
        with self.assertRaisesMessage(VentaInvalida, "elige o escribe el cliente"):
            self.vender(self.cajero, 1, [{"metodo": "CRE", "monto": "10"}])
        with self.assertRaisesMessage(VentaInvalida, "permiso para vender al fiado"):
            self.vender(self.vendedor, 1, [{"metodo": "CRE", "monto": "10"}], cliente_id=self.maria.pk, puede_fiar=False)
        v1 = self.vender(self.cajero, 3, [{"metodo": "EFE", "monto": "10"}, {"metodo": "CRE", "monto": "20"}], cliente_id=self.maria.pk)
        self.assertEqual((v1.cliente, self.maria.saldo, v1.vuelto), (self.maria, D("20"), D("0")))
        with self.assertRaisesMessage(VentaInvalida, "límite es S/ 50.00"):
            self.vender(self.cajero, 4, [{"metodo": "CRE", "monto": "40"}], cliente_id=self.maria.pk)
        self.vender(self.jefe, 4, [{"metodo": "CRE", "monto": "40"}], cliente_id=self.maria.pk, puede_exceder_limite=True)
        self.assertEqual(self.maria.saldo, D("60"))
        with self.assertRaisesMessage(ClienteError, "solo debe S/ 60.00"):
            registrar_abono(self.maria, D("70"), "EFE", self.cajero)
        a = registrar_abono(self.maria, D("25"), "EFE", self.cajero)
        registrar_abono(self.maria, D("5"), "YAP", self.cajero)
        self.assertEqual(self.maria.saldo, D("30"))
        self.assertEqual(total_por_cobrar(), D("30"))
        # la caja del cajero: efectivo de la venta + pago en efectivo; el fiado no es efectivo
        r = calcular(a.sesion_caja)
        self.assertEqual((r["esperado"], r["fiado"], r["abonos"], r["abonos_efectivo"]), (D("135"), D("20"), D("30"), D("25")))
        # anular la venta fiada baja la deuda; anular un pago la sube
        anular_venta(v1, self.jefe, "error")
        self.assertEqual(self.maria.saldo, D("10"))
        anular_abono(a, self.jefe, "billete falso")
        self.assertEqual(self.maria.saldo, D("35"))

    def test_pago_de_caja_cerrada_sale_de_la_caja_actual(self):
        self.vender(self.cajero, 2, [{"metodo": "CRE", "monto": "20"}], cliente_id=self.maria.pk)
        a = registrar_abono(self.maria, D("20"), "EFE", self.cajero)
        cerrar(a.sesion_caja, D("120"), self.cajero)
        anular_abono(a, self.jefe, "devuelto")
        from caja.models import SesionCaja

        egreso = SesionCaja.abierta_de(self.jefe).movimientos.get()
        self.assertEqual((egreso.monto, egreso.automatico), (D("20"), True))

    def test_cliente_al_vuelo(self):
        v = self.vender(self.cajero, 1, [{"metodo": "EFE", "monto": "10"}], cliente_nombre="Pedro", cliente_documento="40987654")
        self.assertEqual(v.cliente.numero_documento, "40987654")
        v2 = self.vender(self.cajero, 1, [{"metodo": "EFE", "monto": "10"}], cliente_nombre="Otro nombre", cliente_documento="40987654")
        self.assertEqual(v2.cliente, v.cliente)  # mismo DNI = mismo cliente
        with self.assertRaisesMessage(VentaInvalida, "RUC no es válido"):
            self.vender(self.cajero, 1, [{"metodo": "EFE", "monto": "10"}], cliente_nombre="X", cliente_documento="20100047219")
        v3 = self.vender(self.cajero, 1, [{"metodo": "CRE", "monto": "10"}], cliente_nombre="Doña Juana")
        self.assertEqual((v3.cliente.nombre, v3.cliente.tipo_documento), ("Doña Juana", "SD"))
        self.assertEqual(Cliente.objects.count(), 3)

    def test_vistas(self):
        self.vender(self.cajero, 2, [{"metodo": "CRE", "monto": "20"}], cliente_id=self.maria.pk)
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse("clientes:lista") + "?ver=deben"), "María")
        r = self.client.get(reverse("clientes:buscar") + "?q=4512")
        self.assertEqual(r.json()["resultados"][0]["saldo"], "20.00")
        self.assertEqual(self.client.post(reverse("clientes:abonar", args=[self.maria.pk]), {"monto": "5", "metodo": "EFE"}).status_code, 403)
        # el vendedor no ve «Fiado» como método de pago
        self.assertNotContains(self.client.get(reverse("ventas:pos")), '"id": "CRE"')
        r = self.client.post(reverse("ventas:registrar"), json.dumps({"items": [{"variante": self.v.pk, "cantidad": "1"}],
                             "pagos": [{"metodo": "CRE", "monto": "10"}], "cliente_id": self.maria.pk}), content_type="application/json")
        self.assertIn("permiso", r.json()["error"])
        self.client.force_login(self.cajero)
        self.assertContains(self.client.get(reverse("ventas:pos")), '"id": "CRE"')
        r = self.client.post(reverse("clientes:abonar", args=[self.maria.pk]), {"monto": "5", "metodo": "EFE"})
        self.assertEqual(self.maria.saldo, D("15"))
        self.assertContains(self.client.get(r["Location"]), "Estado de cuenta")
        self.assertContains(self.client.get(reverse("clientes:imprimir", args=[self.maria.pk]) + f"?pago={self.maria.abonos.latest('id').pk}"), "CONSTANCIA DE PAGO")
        r = self.client.post(reverse("clientes:nuevo"), {"tipo_documento": "RUC", "numero_documento": "20100047218", "nombre": "Banco",
                                                       "limite_credito": "0", "activo": "on"})
        self.assertEqual(Cliente.objects.get(numero_documento="20100047218").nombre, "Banco")
        r = self.client.post(reverse("clientes:nuevo"), {"tipo_documento": "DNI", "numero_documento": "45123678", "nombre": "Dup",
                                                       "limite_credito": "0", "activo": "on"})
        self.assertContains(r, "Ya está registrado")
        self.assertEqual(self.client.get(reverse("clientes:lista") + "?excel=1").status_code, 200)


class CelularTests(TestCase):
    """Una sola forma de reconocer al cliente por su celular, para delivery, reservas y citas."""

    def setUp(self):
        from django.contrib.auth.models import Group, User

        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"]})
        self.u = User.objects.create_user("cajero", password="x-clave-123")
        self.u.groups.add(Group.objects.get(name="Cajero"))

    def test_recordar_y_historial_de_todo_el_negocio(self):
        from datetime import time, timedelta

        from django.utils import timezone

        from mesas.servicios import abrir_delivery
        from reservas.models import Reserva
        from reservas.servicios import guardar, no_vino

        from .servicios import historial, recordar

        c = recordar("Rosa", "987 111 222", "Av. Grau 120", "delivery")
        self.assertEqual(recordar("Otra", "+51987111222"), c)  # mismo celular: mismo cliente, aunque se escriba distinto
        abrir_delivery(self.u, "Rosa", "987111222", "Av. Grau 130")
        c.refresh_from_db()
        self.assertEqual(c.direccion, "Av. Grau 130")  # recuerda la última dirección
        r, _ = guardar(self.u, fecha=timezone.localdate() + timedelta(days=1), hora=time(20), personas=2, nombre="Rosa", telefono="987111222")
        self.assertEqual(r.cliente, c)
        no_vino(r, self.u)
        h = historial("987111222")
        self.assertEqual((h["nombre"], h["pedidos"], h["reservas"], h["no_vino"], h["cliente_id"]), ("Rosa", 1, 1, 1, c.pk))
        self.client.force_login(self.u)
        d = self.client.get("/clientes/celular/", {"tel": "987111222"}).json()
        self.assertTrue(d["conocido"])
        self.assertEqual(d["direccion"], "Av. Grau 130")
        resp = self.client.get(f"/clientes/{c.pk}/")
        self.assertContains(resp, "En el negocio")
        self.assertContains(resp, "no vino")
        self.assertEqual(Reserva.objects.get().cliente, c)
