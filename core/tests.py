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
