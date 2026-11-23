"""Vencimiento del fiado: cada fiado vence a los días de plazo del cliente; con algo vencido no se le fía sin permiso."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir
from core.models import Ajustes, Bitacora
from productos.models import Producto
from productos.servicios import asegurar_variante_unica
from ventas.models import Venta
from ventas.servicios import VentaInvalida, registrar_venta

from .models import Cliente
from .servicios import deudas, registrar_abono, vencidos

D = Decimal


class PlazoFiadoTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"dias_fiado": 15})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        for u in (self.cajero, self.jefe):
            abrir(u, D("100"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Arroz", precio=D("10"), maneja_stock=False))
        self.maria = Cliente.objects.create(tipo_documento="DNI", numero_documento="45123678", nombre="María")
        self.hoy = timezone.localdate()

    def fiar(self, usuario, monto, hace=0, **kw):
        v = registrar_venta(usuario, [{"variante": self.v.pk, "cantidad": str(monto // 10)}], [{"metodo": "CRE", "monto": str(monto)}],
                            cliente_id=self.maria.pk, puede_fiar=True, **kw)
        if hace:
            Venta.objects.filter(pk=v.pk).update(fecha=timezone.now() - timedelta(days=hace))
        return v

    def test_vence_bloquea_y_se_destraba_al_pagar(self):
        self.fiar(self.cajero, 20, hace=3)   # vence en 12 días
        self.fiar(self.cajero, 30, hace=20)  # venció hace 5 días (se fió cuando aún no debía nada)
        filas = deudas(self.maria)
        self.assertEqual([(f["vence"], f["vencido"], f["dias_atraso"]) for f in filas],
                         [(self.hoy - timedelta(days=5), D("30"), 5), (self.hoy + timedelta(days=12), 0, 0)])
        self.assertEqual(vencidos()[self.maria.pk], {"monto": D("30"), "dias": 5})
        with self.assertRaisesMessage(VentaInvalida, "tiene S/ 30.00 vencido"):
            self.fiar(self.cajero, 10)
        # quien puede pasar el límite sí le fía, y queda en la bitácora
        self.fiar(self.jefe, 10, puede_exceder_limite=True)
        self.assertTrue(Bitacora.objects.filter(accion="fiado.con_vencido").exists())
        # paga lo vencido (los pagos van a lo más antiguo) y se le puede volver a fiar
        registrar_abono(self.maria, D("30"), "EFE", self.cajero)
        self.assertEqual(vencidos(), {})
        self.fiar(self.cajero, 10)

    def test_plazo_por_cliente_y_sin_vencimiento(self):
        self.fiar(self.cajero, 30, hace=20)
        self.maria.dias_credito = 30  # cliente de confianza: 30 días
        self.maria.save()
        self.assertEqual(deudas(self.maria)[0]["vence"], self.hoy + timedelta(days=10))
        self.fiar(self.cajero, 10)
        self.maria.dias_credito = None  # vuelve al general (15)
        self.maria.save()
        self.assertIn(self.maria.pk, vencidos())
        Ajustes.objects.filter(pk=1).update(dias_fiado=0)  # el negocio no usa plazos: nada vence
        self.assertEqual(deudas(self.maria)[0]["vence"], None)
        self.fiar(self.cajero, 10)

    def test_pantallas(self):
        Cliente.objects.filter(pk=self.maria.pk).update(telefono="987654321")
        self.fiar(self.cajero, 30, hace=20)
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("clientes:detalle", args=[self.maria.pk]))
        self.assertContains(r, "Lo que falta pagar y cuándo vence")
        self.assertContains(r, "Vencida · 5 días")
        from urllib.parse import unquote

        self.assertIn("S/ 30.00 ya venció", unquote(r.context["wa"]))  # el recordatorio por WhatsApp dice lo vencido
        self.assertIn("(venció el ", unquote(r.context["wa"]))
        self.assertEqual(self.client.get(reverse("clientes:buscar"), {"q": "María"}).json()["resultados"][0]["vencido"], "30.00")
        self.assertContains(self.client.get(reverse("core:inicio")), "1 cliente con fiado vencido")
        r = self.client.get(reverse("clientes:lista"), {"ver": "vencido"})
        self.assertContains(r, "María")
        # cambiar el plazo de un cliente queda en la bitácora
        self.client.post(reverse("clientes:editar", args=[self.maria.pk]), {
            "tipo_documento": "DNI", "numero_documento": "45123678", "nombre": "María", "limite_credito": "0",
            "dias_credito": "30", "activo": "on"})
        self.maria.refresh_from_db()
        self.assertEqual(self.maria.dias_credito, 30)
        self.assertTrue(Bitacora.objects.filter(accion="cliente.plazo").exists())
