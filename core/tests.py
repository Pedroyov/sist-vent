"""Recorrido de humo: todas las pantallas, con cada rol, sobre la demo de restaurante. Ninguna debe dar error 500."""
import re

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver


def _rutas(resolver=None, prefijo=""):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            if str(p.pattern).startswith("admin/"):
                continue
            yield from _rutas(p, prefijo + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefijo + str(p.pattern)


class RecorridoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        call_command("datos_demo", rubro="RES", stdout=StringIO())

    def test_ninguna_pantalla_falla(self):
        rutas = sorted(set(_rutas()))
        fallas = []
        for usuario in ("admin", "gerente", "cajero", "vendedor", "cocina", None):
            self.client.logout()
            if usuario:
                self.client.force_login(User.objects.get(username=usuario))
            for r in rutas:
                if r.startswith(("salir/", "archivos/")):
                    continue
                url = "/" + re.sub(r"<(?:int:)?\w+>", "1", r.replace("^", "").replace("$", ""))
                url = re.sub(r"<str:\w+>", "x", url).replace("<path:ruta>", "x")
                for extra in ("", "?q=a&desde=2026-01-01&hasta=x&estado=todos&page=999&excel=1"):
                    try:
                        resp = self.client.get(url + extra)
                        if resp.status_code >= 500:
                            fallas.append(f"{usuario} {url}{extra} -> {resp.status_code}")
                    except Exception as e:  # noqa: BLE001
                        fallas.append(f"{usuario} {url}{extra} -> {type(e).__name__}: {e}")
        self.assertEqual(fallas, [], "\n".join(fallas))

    def test_anonimo_no_ve_nada(self):
        for url in ("/", "/productos/", "/ventas/", "/ventas/lista/", "/caja/", "/mesas/", "/mesas/cocina/", "/ventas/1/imprimir/",
                    "/configuracion/usuarios/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/ingresar/", resp["Location"])


class RespaldoTests(TestCase):
    def test_respaldo(self):
        import tempfile
        import zipfile
        from io import StringIO
        from pathlib import Path

        from django.db import connection

        if "sqlite" not in connection.settings_dict["ENGINE"] or connection.settings_dict["NAME"].startswith(("file:", ":memory:")):
            self.skipTest("la base de pruebas está en memoria")
        with tempfile.TemporaryDirectory() as tmp:
            call_command("respaldo", carpeta=tmp, guardar=2, stdout=StringIO())
            zips = list(Path(tmp).glob("respaldo_*.zip"))
            self.assertEqual(len(zips), 1)
            self.assertIn("db.sqlite3", zipfile.ZipFile(zips[0]).namelist())


class SeguridadTests(TestCase):
    def test_impresion_en_marco_del_mismo_sitio(self):
        """Las impresiones se hacen en un marco oculto: deben poder mostrarse dentro del propio sistema (y no de otros)."""
        from io import StringIO

        call_command("datos_demo", stdout=StringIO())
        self.client.force_login(User.objects.get(username="gerente"))
        r = self.client.get("/ventas/1/imprimir/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")


class ModulosTests(TestCase):
    """Lo contratado se enciende en Módulos; cocina y delivery necesitan Mesas; productos y ventas son la base."""

    def test_dependencias_y_base(self):
        from .models import Ajustes
        from .permisos import modulos_activos

        a = Ajustes.cargar()
        a.modulos_inactivos = ["mesas"]
        a.save()
        activos = modulos_activos()
        self.assertNotIn("cocina", activos)  # sin mesas no hay cocina ni delivery, aunque estén "encendidos"
        self.assertNotIn("delivery", activos)
        self.assertFalse(a.cocina_pantalla or a.delivery_activo)
        self.assertTrue({"productos", "ventas", "config"} <= activos)
        a.modulos_inactivos = ["productos", "ventas"]  # no se pueden apagar
        a.save()
        self.assertTrue({"productos", "ventas"} <= modulos_activos())
        a.modulos_inactivos = []
        a.save()
        self.assertTrue(a.cocina_pantalla and a.delivery_activo)

    def test_sin_mostrador_el_cajero_cobra_mesas_y_ve_sus_ventas(self):
        from django.contrib.auth.models import Group, User
        from django.urls import reverse

        from .models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["mostrador"]})
        u = User.objects.create_user("caja", password="x-clave-123")
        u.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("ventas:pos")).status_code, 403)
        r = self.client.get(reverse("ventas:lista"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "GESTIÓN")
        self.assertNotContains(r, reverse("ventas:pos") + '"')
