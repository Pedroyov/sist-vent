"""Exportar a Excel / imprimir, tipos de ticketera y la ayuda «?» de cada pantalla."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import get_resolver, reverse

from .ayuda import AYUDA
from .models import Ajustes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def nombres_de_rutas():
    salida = set()

    def recorrer(r, ns=""):
        for p in r.url_patterns:
            if hasattr(p, "url_patterns"):
                recorrer(p, f"{ns}:{p.namespace}".strip(":") if p.namespace else ns)
            elif p.name:
                salida.add(f"{ns}:{p.name}" if ns else p.name)

    recorrer(get_resolver())
    return salida


class ExportarTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": []})
        self.admin = User.objects.create_superuser("admin", password="x-clave-123")
        self.client.force_login(self.admin)

    def test_excel_de_las_pantallas(self):
        from caja.servicios import abrir

        abrir(self.admin, Decimal("50"))
        hoy = date.today().isoformat()
        for url in [reverse("caja:gastos"), reverse("caja:historial"), reverse("compras:lista"), reverse("compras:por_pagar"),
                    reverse("compras:reponer"), reverse("compras:proveedores"), reverse("personal:pagos"), reverse("ventas:conciliar"),
                    reverse("citas:agenda") + f"?fecha={hoy}", reverse("reservas:agenda") + f"?fecha={hoy}"]:
            r = self.client.get(url + ("&" if "?" in url else "?") + "excel=1")
            self.assertEqual((r.status_code, r["Content-Type"]), (200, XLSX), url)
            self.assertIn(".xlsx", r["Content-Disposition"])
        r = self.client.get(reverse("compras:por_pagar"))
        self.assertContains(r, "Imprimir / PDF")
        self.assertContains(r, "excel=1")

    def test_tipos_de_ticketera(self):
        from ventas.models import Venta  # noqa: F401  (el ticket se arma con cualquier venta)
        from productos.models import Producto
        from productos.servicios import asegurar_variante_unica
        from ventas.servicios import registrar_venta

        Ajustes.objects.filter(pk=1).update(vender_sin_caja=True)
        v = registrar_venta(self.admin, [{"variante": asegurar_variante_unica(Producto.objects.create(nombre="Pan", precio=1, maneja_stock=False)).pk,
                                          "cantidad": "1"}], [{"metodo": "EFE", "monto": "1"}])
        for ancho, esperado in ((76, "--ancho: 64mm"), (58, "--ancho: 48mm"), (210, 'data-hoja="1"')):
            Ajustes.objects.filter(pk=1).update(ticket_ancho=ancho)
            self.assertContains(self.client.get(reverse("ventas:imprimir", args=[v.pk])), esperado)

    def test_ayuda_de_cada_pantalla(self):
        rutas = nombres_de_rutas()
        sobran = [k for k in AYUDA if k not in rutas]
        self.assertEqual(sobran, [], "ayuda de pantallas que no existen")
        r = self.client.get(reverse("caja:gastos"))
        self.assertContains(r, 'id="ayuda-pantalla"')
        self.assertContains(r, "Todo lo que salió")
        r = self.client.get(reverse("caja:gasto_nuevo"))  # sin ayuda propia: no sale el botón
        self.assertNotContains(r, 'id="ayuda-pantalla"')
        usuario = User.objects.create_user("cajero", password="x-clave-123")
        usuario.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(usuario)
        self.assertContains(self.client.get(reverse("ventas:pos")), "El punto de venta")
