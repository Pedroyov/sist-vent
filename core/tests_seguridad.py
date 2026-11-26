"""Ingreso seguro: código del celular (TOTP), códigos de respaldo, dispositivo recordado y bloqueo compartido."""
import time

from django.contrib.auth.models import Group, User
from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import reverse

from . import dos_factor as df
from .models import Bitacora, SegundoFactor


def activar(usuario):
    f = SegundoFactor.objects.create(usuario=usuario, secreto=df.nuevo_secreto(), activo=True)
    codigos = df.nuevos_respaldos(f)
    f.save()
    return f, codigos


def codigo_actual(f, desfase=0):
    return df._codigo(f.secreto, int(time.time() // df.PASO) + desfase)


class TotpTests(TestCase):
    def test_vector_del_estandar_y_sin_repetir(self):
        secreto = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238, "12345678901234567890"
        self.assertEqual(df._codigo(secreto, 1), "287082")
        self.assertEqual(df.paso_valido(secreto, "287 082", ahora=59), 1)
        self.assertEqual(df.paso_valido(secreto, "287082", ahora=59 + 30), 1)  # reloj desfasado un paso
        self.assertIsNone(df.paso_valido(secreto, "287082", ahora=59 + 90))   # muy viejo
        self.assertIsNone(df.paso_valido(secreto, "287082", ultimo=1, ahora=59))  # ya usado
        self.assertIsNone(df.paso_valido(secreto, "12345", ahora=59))
        self.assertTrue(df.enlace_app(secreto, User(username="ana")).startswith("otpauth://totp/"))

    def test_bloqueo_en_la_base(self):
        self.assertEqual(caches["seguridad"].__class__.__name__, "DatabaseCache")


class IngresoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefa", password="x-clave-123", first_name="Ana")
        self.admin.groups.add(Group.objects.get(name="Administración"))
        self.f, self.codigos = activar(self.admin)

    def entrar(self, clave="x-clave-123"):
        return self.client.post(reverse("login"), {"username": "jefa", "password": clave, "next": "/caja/"})

    def test_pide_codigo_y_recuerda_dispositivo(self):
        r = self.entrar()
        self.assertRedirects(r, reverse("ingresar_codigo"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)  # con la contraseña sola no entra
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": "000000"})
        self.assertContains(r, "no es correcto")
        usado = codigo_actual(self.f)
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": usado})
        self.assertRedirects(r, "/caja/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso").exists())
        self.assertNotIn(df.COOKIE, r.cookies)  # sin marcar «recordar» no se guarda nada
        # el mismo código no sirve dos veces
        self.client.logout()
        self.entrar()
        self.assertContains(self.client.post(reverse("ingresar_codigo"), {"codigo": usado}), "no es correcto")

    def test_dispositivo_recordado_y_olvidar(self):
        self.entrar()
        self.client.post(reverse("ingresar_codigo"), {"codigo": codigo_actual(self.f), "recordar": "1"})
        self.client.post(reverse("logout"))  # logout() del cliente de pruebas borraría también la cookie
        r = self.entrar()
        self.assertRedirects(r, "/caja/", fetch_redirect_response=False)
        # cambiar la versión (olvidar dispositivos) vuelve a pedirlo
        SegundoFactor.objects.filter(pk=self.f.pk).update(version=self.f.version + 1)
        self.client.post(reverse("logout"))  # logout() del cliente de pruebas borraría también la cookie
        self.assertRedirects(self.entrar(), reverse("ingresar_codigo"), fetch_redirect_response=False)

    def test_codigo_de_respaldo_una_vez(self):
        self.entrar()
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": self.codigos[0].upper()})
        self.assertEqual(r.status_code, 302)
        self.f.refresh_from_db()
        self.assertEqual(len(self.f.respaldos), 7)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.respaldo").exists())
        self.client.logout()
        self.entrar()
        self.assertContains(self.client.post(reverse("ingresar_codigo"), {"codigo": self.codigos[0]}), "no es correcto")

    def test_codigos_errados_bloquean(self):
        self.entrar()
        for _ in range(5):
            self.client.post(reverse("ingresar_codigo"), {"codigo": "111111"})
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": codigo_actual(self.f)})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.entrar(), "Demasiados intentos")

    def test_el_paso_pendiente_vence(self):
        self.entrar()
        s = self.client.session
        s[df.PENDIENTE]["t"] -= df.MINUTOS_PARA_CODIGO * 60 + 1
        s.save()
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": codigo_actual(self.f)})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)

    def test_administracion_quita_el_codigo_de_otro(self):
        otro = User.objects.create_user("jefe2", password="x-clave-123")
        otro.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(otro)
        r = self.client.get(reverse("core:usuario_lista"))
        self.assertContains(r, "Quitar código")
        self.client.post(reverse("core:quitar_codigo", args=[self.admin.pk]))
        self.f.refresh_from_db()
        self.assertFalse(self.f.activo)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.2fa_quitado").exists())
        cajero = User.objects.create_user("caja", password="x-clave-123")
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        self.assertIn(self.client.post(reverse("core:quitar_codigo", args=[otro.pk])).status_code, (302, 403))
        self.assertFalse(SegundoFactor.objects.filter(usuario=otro).exists())


@override_settings(DOS_FACTOR_OBLIGATORIO=True)
class ObligatorioTests(TestCase):
    def test_administracion_debe_activarlo_y_el_cajero_no(self):
        admin = User.objects.create_user("jefa", password="x-clave-123")
        admin.groups.add(Group.objects.get(name="Administración"))
        cajero = User.objects.create_user("caja", password="x-clave-123")
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        self.assertEqual(self.client.get(reverse("core:inicio")).status_code, 200)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get(reverse("core:inicio")), reverse("seguridad"), fetch_redirect_response=False)
        r = self.client.get(reverse("seguridad"))
        self.assertContains(r, "<svg")
        secreto = self.client.session["dos_factor_nuevo"]
        self.assertContains(self.client.post(reverse("seguridad"), {"accion": "activar", "codigo": "000000"}), "no coincide")
        r = self.client.post(reverse("seguridad"), {"accion": "activar", "codigo": df._codigo(secreto, int(time.time() // 30))})
        self.assertContains(r, "Guárdalos ahora")
        self.assertEqual(len(r.context["codigos"]), 8)
        self.assertEqual(self.client.get(reverse("core:inicio")).status_code, 200)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.2fa_activado").exists())
        # cambiar de celular pide el código actual y vuelve a obligar a activarlo
        f = SegundoFactor.objects.get(usuario=admin)
        self.client.post(reverse("seguridad"), {"accion": "cambiar", "codigo": "000000"})
        f.refresh_from_db()
        self.assertTrue(f.activo)
        f.ultimo_paso = 0
        f.save()
        self.client.post(reverse("seguridad"), {"accion": "cambiar", "codigo": df._codigo(f.secreto, int(time.time() // 30))})
        f.refresh_from_db()
        self.assertFalse(f.activo)
        self.assertRedirects(self.client.get(reverse("core:inicio")), reverse("seguridad"), fetch_redirect_response=False)


class SegundoPasoDelNegocioTests(TestCase):
    """El segundo paso lo elige cada negocio: no pedir, código por correo o app. Y el aviso de equipo nuevo."""

    def setUp(self):
        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"nombre": "Pollería Rosa"})
        self.admin = User.objects.create_user("jefa", password="x-clave-123", first_name="Ana", email="ana@ejemplo.com")
        self.admin.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("caja", password="x-clave-123", email="caja@ejemplo.com")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))

    def modo(self, valor):
        from core.models import Ajustes

        Ajustes.objects.filter(pk=1).update(codigo_ingreso=valor)

    def entrar(self, usuario="jefa"):
        return self.client.post(reverse("login"), {"username": usuario, "password": "x-clave-123", "next": "/caja/"})

    def test_codigo_por_correo(self):
        from django.core import mail

        self.modo("COR")
        r = self.entrar()
        self.assertRedirects(r, reverse("ingresar_codigo"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        codigo = mail.outbox[0].subject[:6]
        self.assertTrue(codigo.isdigit())
        self.assertContains(self.client.get(reverse("ingresar_codigo")), "an•••@ejemplo.com")
        self.assertContains(self.client.post(reverse("ingresar_codigo"), {"codigo": "000000" if codigo != "000000" else "111111"}), "no es correcto")
        self.client.post(reverse("ingresar_codigo"), {"accion": "reenviar"})  # pide otro: el anterior ya no sirve
        self.assertEqual(len(mail.outbox), 2)
        r = self.client.post(reverse("ingresar_codigo"), {"codigo": mail.outbox[1].subject[:6], "recordar": "1"})
        self.assertRedirects(r, "/caja/", fetch_redirect_response=False)
        self.assertIn(df.COOKIE, r.cookies)
        self.client.post(reverse("logout"))
        self.assertRedirects(self.entrar(), "/caja/", fetch_redirect_response=False)  # equipo recordado: no pide código
        self.assertEqual(len(mail.outbox), 2)
        # el cajero nunca lo necesita
        self.client.post(reverse("logout"))
        self.assertRedirects(self.entrar("caja"), "/caja/", fetch_redirect_response=False)

    def test_sin_correo_entra_con_aviso(self):
        self.modo("COR")
        User.objects.filter(pk=self.admin.pk).update(email="")
        r = self.entrar()
        self.assertRedirects(r, "/caja/", fetch_redirect_response=False)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.sin_correo").exists())

    def test_app_obligatoria_por_el_negocio(self):
        self.modo("APP")
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("core:inicio")), reverse("seguridad"), fetch_redirect_response=False)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("core:inicio")).status_code, 200)

    def test_aviso_de_equipo_nuevo(self):
        from django.core import mail

        r = self.entrar()  # sin segundo paso: entra directo, pero le llega el aviso
        self.assertRedirects(r, "/caja/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("equipo nuevo", mail.outbox[0].subject)
        self.client.post(reverse("logout"))
        self.entrar()  # mismo equipo: ya no avisa
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(reverse("logout"))
        self.entrar("caja")  # el cajero no recibe avisos
        self.assertEqual(len(mail.outbox), 1)

    def test_clave_larga_para_administracion(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "10 caracteres"):
            validate_password("Pol-2026x", user=self.admin)
        validate_password("Pol-2026x", user=self.cajero)  # 9 caracteres: al cajero le basta

    def test_solo_administracion_cambia_el_segundo_paso(self):
        from core.forms import DatosNegocioForm

        self.assertTrue(DatosNegocioForm(puede_seguridad=False).fields["codigo_ingreso"].disabled)
        self.assertFalse(DatosNegocioForm().fields["codigo_ingreso"].disabled)


class BloqueoYSoporteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefa", password="x-clave-123")
        self.admin.groups.add(Group.objects.get(name="Administración"))
        self.cajero = User.objects.create_user("caja", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))

    def fallar(self, usuario, n):
        for _ in range(n):
            self.client.post(reverse("login"), {"username": usuario, "password": "mala"})

    def test_desbloquear_desde_usuarios(self):
        from core.forms import LoginForm

        self.assertEqual(LoginForm.MAX_IP, 40)
        self.fallar("caja", 5)
        r = self.client.post(reverse("login"), {"username": "caja", "password": "x-clave-123"})
        self.assertContains(r, "pide a Administración que te desbloquee")
        self.client.force_login(self.admin)
        lista = self.client.get(reverse("core:usuario_lista"))
        self.assertContains(lista, "Bloqueado")
        self.client.post(reverse("core:usuario_desbloquear", args=[self.cajero.pk]))
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.desbloqueado").exists())
        self.client.post(reverse("logout"))
        r = self.client.post(reverse("login"), {"username": "caja", "password": "x-clave-123"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.cajero.pk)

    def test_quien_entra_bien_no_cuenta_para_la_conexion(self):
        from core.forms import cache_seguridad, claves_ingreso

        self.fallar("caja", 3)
        self.client.post(reverse("login"), {"username": "caja", "password": "x-clave-123"})
        k_ip = claves_ingreso(self.client.get("/").wsgi_request, "caja")[1]
        self.assertEqual(cache_seguridad().get(k_ip, 0), 0)

    def test_comandos_de_soporte(self):
        from io import StringIO

        from django.core.management import call_command

        from core.models import Ajustes

        f, _ = activar(self.admin)
        salida = StringIO()
        call_command("quitar_codigo", "--listar", stdout=salida)
        self.assertIn("jefa", salida.getvalue())
        call_command("quitar_codigo", "jefa", nota="llamó, DNI verificado", stdout=StringIO())
        f.refresh_from_db()
        self.assertFalse(f.activo)
        self.assertTrue(Bitacora.objects.filter(accion="ingreso.2fa_quitado", descripcion__contains="soporte").exists())
        Ajustes.objects.update_or_create(pk=1, defaults={"codigo_ingreso": "COR"})
        call_command("quitar_codigo", "--apagar", stdout=StringIO())
        self.assertEqual(Ajustes.cargar().codigo_ingreso, "")
        self.fallar("caja", 5)
        call_command("desbloquear", "caja", stdout=StringIO())
        self.client.post(reverse("login"), {"username": "caja", "password": "x-clave-123"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.cajero.pk)
        call_command("desbloquear", "--todos", stdout=StringIO())
