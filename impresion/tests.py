"""Impresión automática: la cola en el servidor y la estación de impresión (PC de caja)."""
import json
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir
from core.models import Ajustes
from mesas.models import Mesa, Zona
from mesas.servicios import abrir_cuenta, agregar
from productos.models import Categoria, Producto
from productos.servicios import asegurar_variante_unica

from .models import Trabajo
from .servicios import tomar


class ImpresionAutomaticaTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"], "funciones_inactivas": [], "imprimir_auto": True})
        self.cajero = User.objects.create_user("caja", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        abrir(self.cajero, D("0"))
        self.lomo = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("25"), maneja_stock=False))
        bar = Categoria.objects.create(nombre="Tragos", area="BAR")
        self.pisco = asegurar_variante_unica(Producto.objects.create(nombre="Pisco sour", precio=D("18"), maneja_stock=False, categoria=bar))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")

    def post(self, nombre, datos):
        return self.client.post(reverse(nombre), json.dumps(datos), content_type="application/json")

    def test_se_encola_y_una_sola_estacion_lo_imprime(self):
        # el mozo envía a cocina desde el celular: una comanda por área
        self.client.force_login(self.mozo)
        c = abrir_cuenta(self.mozo, self.mesa, 2)
        with self.captureOnCommitCallbacks(execute=True):
            self.post_agregar(c)
        self.assertEqual(sorted(Trabajo.objects.values_list("tipo", "descripcion")),
                         [("COM", "Comanda · Mesa 1"), ("COM", "Comanda · Mesa 1 (barra)")])
        # venta en Vender: el ticket
        self.client.force_login(self.cajero)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("ventas:registrar", {"items": [{"variante": self.lomo.pk, "cantidad": "1"}], "pagos": [{"metodo": "EFE", "monto": "25"}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Trabajo.objects.filter(tipo="TIC").exists())
        # dos estaciones a la vez: cada trabajo lo toma una sola
        tomados = []
        for clave in ("pc-1", "pc-2", "pc-1", "pc-2"):
            d = self.post("impresion:siguiente", {"clave": clave}).json()
            if d["trabajo"]:
                tomados.append(d["trabajo"]["id"])
        self.assertEqual(len(tomados), len(set(tomados)))
        self.assertEqual(len(tomados), 3)
        self.assertIsNone(self.post("impresion:siguiente", {"clave": "pc-1"}).json()["trabajo"])
        # la estación puede abrir lo que imprime (la comanda también, siendo caja)
        com = Trabajo.objects.filter(tipo="COM").first()
        self.assertEqual(self.client.get(com.url).status_code, 200)
        # avisa: impreso, o error (vuelve a la cola y tras 4 intentos queda como error)
        ok = Trabajo.objects.get(pk=tomados[0])
        self.post("impresion:listo", {"clave": ok.estacion.clave, "id": ok.pk, "ok": True})
        ok.refresh_from_db()
        self.assertEqual(ok.estado, "IMP")
        mal = Trabajo.objects.get(pk=tomados[1])
        self.post("impresion:listo", {"clave": mal.estacion.clave, "id": mal.pk, "ok": False, "error": "sin papel"})
        mal.refresh_from_db()
        self.assertEqual((mal.estado, mal.error), ("PEN", "sin papel"))
        Trabajo.objects.filter(pk=mal.pk).update(intentos=4, estado="TOM")
        self.post("impresion:listo", {"clave": mal.estacion.clave, "id": mal.pk, "ok": False})
        mal.refresh_from_db()
        self.assertEqual(mal.estado, "ERR")
        # una estación que se apagó a medio imprimir: el trabajo vuelve a la cola
        tercero = Trabajo.objects.get(pk=tomados[2])
        Trabajo.objects.filter(pk=tercero.pk).update(tomado_en=timezone.now() - timedelta(minutes=5))
        self.assertEqual(tomar(tercero.estacion).pk, tercero.pk)
        # la cola: reimprimir crea una copia; el Inicio no avisa mientras la estación responde
        self.client.post(reverse("impresion:cola"), {"trabajo": mal.pk, "accion": "reimprimir"})
        self.assertTrue(Trabajo.objects.filter(copia=True, url=mal.url).exists())
        self.assertNotContains(self.client.get(reverse("core:inicio")), "no responde")

    def post_agregar(self, c):
        return self.post_url(reverse("mesas:agregar", args=[c.pk]), {"enviar": True, "items": [{"variante": self.lomo.pk, "cantidad": 1},
                                                                                              {"variante": self.pisco.pk, "cantidad": 2}]})

    def post_url(self, url, datos):
        return self.client.post(url, json.dumps(datos), content_type="application/json")

    def test_imprimir_desde_otro_equipo_y_avisos(self):
        self.client.force_login(self.cajero)
        self.assertEqual(self.post("impresion:enviar", {"url": "/admin/"}).status_code, 400)
        self.assertEqual(self.post("impresion:enviar", {"url": "https://otro.com/x"}).status_code, 400)
        c = abrir_cuenta(self.mozo, self.mesa, 2)
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 1}], self.mozo)
        d = self.post("impresion:enviar", {"url": reverse("mesas:precuenta", args=[c.pk])}).json()
        self.assertEqual(d, {"ok": True, "estacion": False})  # sin estación: queda en cola
        self.assertTrue(Trabajo.objects.filter(tipo="PRE", copia=True).exists())
        self.assertContains(self.client.get(reverse("core:inicio")), "La estación de impresión no responde")
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, 'data-cola="1"')
        self.assertContains(self.client.get(reverse("impresion:estacion")), "--kiosk-printing")

    def test_apagada_no_encola(self):
        Ajustes.objects.filter(pk=1).update(imprimir_auto=False)
        self.client.force_login(self.cajero)
        with self.captureOnCommitCallbacks(execute=True):
            self.post("ventas:registrar", {"items": [{"variante": self.lomo.pk, "cantidad": "1"}], "pagos": [{"metodo": "EFE", "monto": "25"}]})
        self.assertFalse(Trabajo.objects.exists())
        self.assertContains(self.client.get(reverse("ventas:pos")), 'data-cola=""')
