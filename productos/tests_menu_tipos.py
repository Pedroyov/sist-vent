"""Menú del día por tipos (económico, ejecutivo) con platos propios o compartidos, bebida y postre, y su interruptor."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Ajustes

from .models import GrupoOpciones, Opcion, Producto
from .servicios import OpcionInvalida, menu_texto, menu_tipos, resolver_opciones


class MenuPorTiposTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": [], "rubro": "RES",
                                                         "nombre": "El Buen Sabor", "nivel_pedido": 2})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(self.cajero)
        self.url = reverse("productos:menu")

    def post(self, **datos):
        return self.client.post(self.url, datos)

    def test_tipos_con_platos_propios_compartidos_y_bebida(self):
        self.assertContains(self.client.get(self.url), "Empezar")
        self.post(accion="crear", nombre="Menú económico", precio="10", bebida="1")
        eco = Producto.objects.get(nombre="Menú económico")
        self.assertEqual((eco.precio, eco.categoria.nombre), (Decimal("10"), "Menú del día"))
        self.assertEqual(sorted(g.nombre for g in eco.grupos.all()), ["Bebida", "Entrada (Menú económico)", "Segundo (Menú económico)"])
        # el ejecutivo: mismas entradas, segundos propios, sin bebida y con postre
        self.post(accion="nuevo_tipo", nombre="Menú ejecutivo", precio="15", entradas=str(eco.pk), segundos="", postre="1")
        eje = Producto.objects.get(nombre="Menú ejecutivo")
        self.assertEqual(sorted(g.nombre for g in eje.grupos.all()), ["Entrada (Menú económico)", "Postre", "Segundo (Menú ejecutivo)"])
        r = self.post(accion="nuevo_tipo", nombre="Menú ejecutivo", precio="15")
        self.assertEqual(Producto.objects.filter(nombre="Menú ejecutivo").count(), 1)  # no se repite
        # platos de hoy
        g = {x.nombre: x for x in GrupoOpciones.objects.filter(diario=True)}
        for grupo, plato in [("Entrada (Menú económico)", "Sopa"), ("Segundo (Menú económico)", "Arroz con pollo"),
                             ("Segundo (Menú ejecutivo)", "Lomo saltado"), ("Bebida", "Chicha"), ("Postre", "Gelatina")]:
            self.post(accion="agregar", grupo=str(g[grupo].pk), nombre=plato)
        tipos = {t.nombre: t for t in menu_tipos()}
        self.assertEqual(tipos["Menú ejecutivo"].diarios[0].con, ["Menú económico"])  # la entrada compartida avisa
        r = self.client.get(self.url)
        self.assertContains(r, "también Menú económico")
        texto = menu_texto("El Buen Sabor")
        self.assertIn("*Menú económico · S/ 10.00*", texto)
        self.assertIn("_Bebida:_ Chicha", texto)
        self.assertIn("_Segundo:_ Lomo saltado", texto)
        self.assertNotIn("Arroz con pollo", texto.split("*Menú ejecutivo")[1])  # cada tipo con sus segundos
        # pedir el ejecutivo: entrada, segundo y postre
        ops = {o.nombre: o.pk for o in Opcion.objects.all()}
        foto, extra, _ = resolver_opciones(eje, [ops["Sopa"], ops["Lomo saltado"], ops["Gelatina"]])
        self.assertEqual(([o["n"] for o in foto], extra), (["Sopa", "Lomo saltado", "Gelatina"], Decimal("0.00")))
        with self.assertRaises(OpcionInvalida):
            resolver_opciones(eje, [ops["Sopa"], ops["Arroz con pollo"], ops["Gelatina"]])  # segundo de otro menú
        # quitar la bebida del económico y ponerla al ejecutivo
        self.post(accion="extras", tipo=str(eco.pk))
        self.post(accion="extras", tipo=str(eje.pk), bebida="1", postre="1")
        self.assertFalse(eco.grupos.filter(nombre="Bebida").exists())
        self.assertTrue(eje.grupos.filter(nombre="Bebida").exists())

    def test_interruptor_del_menu(self):
        self.assertContains(self.client.get(reverse("core:inicio")), self.url)
        Ajustes.objects.filter(pk=1).update(funciones_inactivas=["menu"])
        self.assertNotContains(self.client.get(reverse("core:inicio")), self.url)
        self.assertRedirects(self.client.get(self.url), reverse("core:inicio"))
        # con el nivel Sencillo avisa que necesita «Con opciones»
        Ajustes.objects.filter(pk=1).update(funciones_inactivas=[], nivel_pedido=1)
        self.assertContains(self.client.get(self.url), "Con opciones")
