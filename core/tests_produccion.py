"""Antes del primer cliente: el rubro no enciende módulos, secretos cifrados, crear_empresa, fotos en cualquier almacén
(disco o Spaces), /salud/ y respaldo."""
import io
import tempfile
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .cifrado import PREFIJO, cifrar, descifrar
from .models import Ajustes, Rubro, SegundoFactor

MEMORIA = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
           "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def png(tam=(1200, 900), color=(200, 30, 30)):
    from PIL import Image

    salida = io.BytesIO()
    Image.new("RGB", tam, color).save(salida, "PNG")
    return salida.getvalue()


class ProduccionTests(TestCase):
    def test_cambiar_rubro_no_enciende_modulos(self):
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        a = Ajustes.cargar()
        a.modulos_inactivos = ["mesas", "cocina", "reservas"]
        a.save()
        self.client.force_login(jefe)
        r = self.client.post(reverse("core:datos_negocio"), {
            "rubro": Rubro.RESTAURANTE, "nombre": "Sabor", "nombre_corto": "Sabor", "color": "#0d6efd", "ticket_ancho": 80,
            "metodos": ["YAP"], "funciones": ["variantes"], "descuentos_activos": "on", "delivery_costo": "0", "nivel_pedido": 2}, follow=True)
        a.refresh_from_db()
        self.assertEqual(a.rubro, Rubro.RESTAURANTE)
        self.assertFalse(a.tiene_modulo("mesas"))  # los módulos los decide el administrador principal
        self.assertContains(r, "Pídele al administrador principal")

    def test_secretos_cifrados(self):
        from facturacion.models import Config

        c = Config.cargar() if hasattr(Config, "cargar") else Config.objects.create()
        c.token = "mi-token-secreto"
        c.save()
        with connection.cursor() as cur:
            cur.execute("SELECT token FROM facturacion_config WHERE id = %s", [c.pk])
            crudo = cur.fetchone()[0]
        self.assertTrue(crudo.startswith(PREFIJO))
        self.assertNotIn("mi-token", crudo)
        c.refresh_from_db()
        self.assertEqual(c.token, "mi-token-secreto")
        u = User.objects.create_user("ana", password="x-clave-123")
        f = SegundoFactor.objects.create(usuario=u, secreto="JBSWY3DPEHPK3PXP")
        with connection.cursor() as cur:
            cur.execute("SELECT secreto FROM core_segundofactor WHERE id = %s", [f.pk])
            self.assertTrue(cur.fetchone()[0].startswith(PREFIJO))
        f.refresh_from_db()
        self.assertEqual(f.secreto, "JBSWY3DPEHPK3PXP")
        self.assertEqual(descifrar("texto-de-antes"), "texto-de-antes")  # lo guardado antes de cifrar se lee igual
        cifrado = cifrar("hola")
        with self.settings(CLAVE_CIFRADO="otra-clave-distinta"), self.assertLogs("core.cifrado", "ERROR"):
            self.assertEqual(descifrar(cifrado), "")  # con otra clave no se puede leer

    def test_crear_empresa(self):
        salida = StringIO()
        call_command("crear_empresa", nombre="Pollería El Buen Sabor", rubro="RES", usuario="carlos", nombre_admin="Carlos Ruiz",
                     ruc="20123456789", stdout=salida)
        a = Ajustes.cargar()
        self.assertEqual((a.nombre, a.rubro, a.ruc), ("Pollería El Buen Sabor", "RES", "20123456789"))
        self.assertTrue(a.tiene_modulo("mesas"))
        u = User.objects.get(username="carlos")
        self.assertTrue(u.is_superuser)
        clave = salida.getvalue().split("clave temporal: ")[1].split()[0]
        self.assertTrue(u.check_password(clave))
        with self.assertRaisesMessage(CommandError, "ya tiene usuarios"):
            call_command("crear_empresa", nombre="Otra", rubro="TIE", usuario="otro", stdout=StringIO())

    @override_settings(STORAGES=MEMORIA)
    def test_fotos_en_cualquier_almacen(self):
        from productos.models import Producto

        p = Producto.objects.create(nombre="Torta", precio=10, imagen=SimpleUploadedFile("torta.png", png(), "image/png"))
        p.procesar_imagen()  # sin rutas de disco: sirve igual con Spaces
        from PIL import Image

        with storages["default"].open(p.imagen.name) as f, Image.open(f) as im:
            self.assertEqual(max(im.size), 800)
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(jefe)
        r = self.client.get(f"/archivos/{p.imagen.name}")
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        self.assertEqual(self.client.get("/archivos/productos/../../config/settings.py").status_code, 404)
        self.assertEqual(self.client.get("/archivos/productos/no-existe.png").status_code, 404)
        a = Ajustes.cargar()
        a.logo = SimpleUploadedFile("logo.png", png((300, 120)), "image/png")
        a.save()
        a.generar_iconos()
        self.assertTrue(storages["default"].exists("negocio/icono-192.png"))
        self.client.logout()
        self.assertEqual(self.client.get("/archivos/negocio/logo.png").status_code, 200)  # el logo es público

    def test_salud_y_respaldo(self):
        r = self.client.get("/salud/", HTTP_HOST="10.0.0.7")  # el chequeo del hosting llega con su IP interna
        self.assertEqual((r.status_code, r.content), (200, b"ok"))
        with self.assertRaisesMessage(CommandError, "SPACES_BUCKET"):
            call_command("respaldo", carpeta=tempfile.gettempdir(), nube=True, stdout=StringIO())
