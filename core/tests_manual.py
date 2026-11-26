"""El Manual de usuario dentro del sistema y el enlace desde el «?» de cada pantalla."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.management.commands.generar_manual import id_seccion
from core.models import Ajustes


class ManualTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": []})
        u = User.objects.create_user("cajero", password="x-clave-123")
        u.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(u)

    def test_manual_y_enlace_desde_la_ayuda(self):
        self.assertEqual((id_seccion("6.3"), id_seccion("6."), id_seccion("10")), ("s-6-3", "s-6", "s-10"))
        r = self.client.get(reverse("core:manual"))
        self.assertContains(r, 'id="s-6-3"')  # cada sección con su ancla
        self.assertContains(r, 'href="#s-7-2"')  # el índice
        self.assertContains(r, "buscar-manual")
        self.assertContains(r, "Descargar PDF")
        self.assertContains(self.client.get(reverse("core:inicio")), reverse("core:manual"))  # en el menú del usuario
        self.assertContains(self.client.get(reverse("caja:mi_caja")), reverse("core:manual") + "#s-6-1")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("core:manual")).status_code, 302)
