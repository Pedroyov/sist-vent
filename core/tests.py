"""Recorrido de humo: todas las pantallas, con cada rol, sobre la demo de restaurante. Ninguna debe dar error 500."""
import re

from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
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
    """Lo contratado se enciende en Módulos; la cocina necesita Mesas (el delivery no); productos y ventas son la base."""

    def test_dependencias_y_base(self):
        from .models import Ajustes
        from .permisos import modulos_activos

        a = Ajustes.cargar()
        a.modulos_inactivos = ["mesas"]
        a.save()
        activos = modulos_activos()
        self.assertNotIn("cocina", activos)  # sin mesas no hay cocina, aunque esté "encendida"
        self.assertIn("delivery", activos)  # el delivery sirve también a una tienda
        self.assertFalse(a.cocina_pantalla)
        self.assertTrue(a.delivery_activo)
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


class RubrosTests(TestCase):
    """El tipo de negocio decide cómo empieza el sistema, sin apagar lo que ya se usa."""

    def setUp(self):
        from django.contrib.auth.models import Group, User

        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.admin = User.objects.create_superuser("root", password="x-clave-123")

    def test_instalacion_nueva_empieza_simple(self):
        from .models import Ajustes

        a = Ajustes.cargar()
        self.assertTrue(a.usa_variantes)
        self.assertFalse(a.usa_combos or a.usa_servicios or a.usa_agotados)
        self.assertEqual(a.nivel_pedido, 1)
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("productos:nuevo"))
        self.assertNotContains(r, 'value="C"')
        self.assertNotContains(r, 'value="S"')
        self.assertNotContains(self.client.get(reverse("core:inicio")), reverse("productos:agotados"))

    def test_cambiar_de_rubro_no_apaga_lo_que_se_usa(self):
        from productos.models import Producto

        from .models import Ajustes, Rubro
        from .rubros import aplicar

        a = Ajustes.cargar()
        aplicar(a, Rubro.RESTAURANTE)
        self.assertTrue(a.usa_combos and a.usa_agotados and a.usa_variantes)
        self.assertEqual(a.nivel_pedido, 2)
        Producto.objects.create(nombre="Menú + bebida", precio=15, tipo=Producto.Tipo.COMBO, maneja_stock=False)
        a.rubro = Rubro.TIENDA
        encendidas, apagadas = aplicar(a)
        self.assertTrue(a.usa_combos)  # hay un combo: no se oculta
        self.assertFalse(a.usa_agotados)
        self.assertIn("Agotados del día", apagadas)
        self.assertEqual(a.nivel_pedido, 1)

    def test_pantallas(self):
        from .models import Ajustes, Rubro

        self.client.force_login(self.jefe)
        a = Ajustes.cargar()
        datos = {"rubro": Rubro.PELUQUERIA, "nombre": "Estilo", "nombre_corto": "Estilo", "color": "#0d6efd", "ticket_ancho": 80,
                 "metodos": ["YAP"], "funciones": ["variantes"], "descuentos_activos": "on", "delivery_costo": "0"}
        r = self.client.post(reverse("core:datos_negocio"), datos)
        self.assertRedirects(r, reverse("core:datos_negocio"))
        a.refresh_from_db()
        self.assertTrue(a.usa_servicios)  # al cambiar a peluquería se activan los servicios
        datos["funciones"] = ["servicios"]
        self.client.post(reverse("core:datos_negocio"), datos)
        a.refresh_from_db()
        self.assertFalse(a.usa_variantes)  # el dueño también puede ocultarlas a mano
        # el administrador principal aplica los módulos recomendados
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("core:modulos")), "Recomendado para")
        a.rubro = Rubro.ACADEMIA
        a.save()
        self.client.post(reverse("core:modulos"), {"accion": "recomendado"})
        a.refresh_from_db()
        self.assertTrue(a.tiene_modulo("cobranzas"))
        self.assertFalse(a.tiene_modulo("mesas"))

    def test_palabras_segun_el_negocio(self):
        from .models import Ajustes, Rubro

        a = Ajustes.cargar()
        a.modulos_inactivos = []
        a.rubro = Rubro.RESTAURANTE
        a.save()
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("core:inicio"))
        self.assertContains(r, "<p>Carta <i")
        self.assertContains(r, "Venta rápida")
        a.rubro = Rubro.ACADEMIA
        a.save()
        r = self.client.get(reverse("cobranzas:planes"))
        self.assertContains(r, "Mensualidades")
        self.assertContains(r, "Alumnos y socios")


class TurnosTests(TestCase):
    """Base común de reservas y citas (core/turnos.py)."""

    def test_textos_y_cierre_de_pasadas_para_los_dos(self):
        from datetime import date, time, timedelta

        from django.contrib.auth.models import User
        from django.utils import timezone

        from citas.models import Cita
        from personal.models import Persona
        from reservas.models import Reserva

        from . import turnos

        hoy = date(2026, 11, 17)  # martes
        self.assertEqual(turnos.hora_texto(time(20, 30)), "8:30 pm")
        self.assertEqual(turnos.hora_texto(9 * 60), "9:00 am")
        self.assertEqual(turnos.dia_texto(hoy + timedelta(days=1), hoy), "mañana")
        self.assertEqual(turnos.dia_texto(hoy + timedelta(days=2), hoy), "el jueves 19/11")
        self.assertEqual(turnos.dia_corto(hoy + timedelta(days=2), hoy), "Jueves 19/11")
        u = User.objects.create_user("x", password="x-clave-123")
        ayer = timezone.localdate() - timedelta(days=1)
        r = Reserva.objects.create(fecha=ayer, hora=time(20), nombre="A", creada_por=u)
        c = Cita.objects.create(fecha=ayer, inicio=time(10), fin=time(10, 30), profesional=Persona.objects.create(nombre="P"), nombre="B",
                                creada_por=u)
        self.assertEqual((turnos.cerrar_pasadas(Reserva), turnos.cerrar_pasadas(Cita)), (1, 1))
        r.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual((r.estado, c.estado), ("NOV", "NOV"))
        self.assertEqual((r.momento.hour, c.momento.hour), (20, 10))
        with self.assertRaisesMessage(ValueError, "La reserva ya está como «No vino»"):
            turnos.cambiar_estado(r, u, "CON", turnos.TurnoBase.ACTIVAS)


class WhatsappTests(TestCase):
    def test_enlace_unico(self):
        from core.utils import enlace_whatsapp

        self.assertEqual(enlace_whatsapp("986 111 222"), "https://wa.me/51986111222")
        self.assertEqual(enlace_whatsapp("986111222", "Hola ñ"), "https://wa.me/51986111222?text=Hola%20%C3%B1")
        self.assertEqual(enlace_whatsapp("", "Hola"), "")  # sin número no hay botón
        self.assertEqual(enlace_whatsapp(None, "a\nb"), "https://wa.me/?text=a%0Ab")  # compartir


class FechasYAdminTests(TestCase):
    def test_filtro_por_dias_locales(self):
        """`dias()` cuenta por día de Lima aunque la base guarde en UTC (una venta a las 23:30 es de ese día)."""
        from datetime import date, datetime
        from decimal import Decimal

        from django.utils import timezone

        from core.utils import dias
        from ventas.models import Venta

        u = User.objects.create_user("x", password="x-clave-123")
        tarde = timezone.make_aware(datetime(2026, 11, 19, 23, 30))
        temprano = timezone.make_aware(datetime(2026, 11, 20, 0, 10))
        for n, f in ((1, tarde), (2, temprano)):
            Venta.objects.create(numero=n, fecha=f, usuario=u, subtotal=Decimal("1"), total=Decimal("1"))
        self.assertEqual(list(Venta.objects.filter(**dias("fecha", date(2026, 11, 19))).values_list("numero", flat=True)), [1])
        self.assertEqual(Venta.objects.filter(**dias("fecha", date(2026, 11, 19), date(2026, 11, 20))).count(), 2)
        self.assertEqual(Venta.objects.filter(**dias("fecha", date(2026, 11, 19), antes_de=date(2026, 11, 20))).count(), 1)

    def test_admin_solo_si_se_enciende(self):
        """Sin ADMIN_ACTIVO (por defecto en producción) no existe /admin/ ni su enlace en el menú."""
        import importlib

        from django.test import override_settings
        from django.urls import clear_url_caches

        import config.urls

        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(__import__("django.contrib.auth.models", fromlist=["Group"]).Group.objects.get(name="Administración"))
        self.client.force_login(jefe)
        try:
            for activo, codigo in ((False, 404), (True, 302)):
                with override_settings(ADMIN_ACTIVO=activo):
                    importlib.reload(config.urls)
                    clear_url_caches()
                    self.assertEqual(self.client.get("/admin/").status_code, codigo)
                    if not activo:
                        self.assertNotContains(self.client.get(reverse("core:inicio")), "Admin de Django")
        finally:
            importlib.reload(config.urls)
            clear_url_caches()
