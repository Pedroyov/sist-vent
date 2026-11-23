"""Promociones: 2×1, % y precio especial, con fechas, días y horario; se aplican solas y no se suman."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Ajustes, Bitacora
from ventas.devoluciones import devolver
from ventas.servicios import armar_lineas, registrar_venta

from .models import Categoria, ListaPrecios, PrecioEspecial, Producto, Promocion, Variante
from .servicios import asegurar_variante_unica

D = Decimal


class PromocionesTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True, "funciones_inactivas": [],
                                                         "metodos_pago": ["EFE", "YAP"]})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.utiles = Categoria.objects.create(nombre="Cuadernos")
        self.chicha = asegurar_variante_unica(Producto.objects.create(nombre="Chicha", precio=D("4"), maneja_stock=False))
        self.cuaderno = asegurar_variante_unica(Producto.objects.create(nombre="Cuaderno A4", precio=D("10"), categoria=self.utiles,
                                                                         maneja_stock=False))
        self.polo = Producto.objects.create(nombre="Polo", precio=D("30"), maneja_stock=False)
        self.s = Variante.objects.create(producto=self.polo, nombre="S")
        self.xl = Variante.objects.create(producto=self.polo, nombre="XL", precio=D("36"))
        self.dos_por_uno = Promocion.objects.create(nombre="2×1 chicha", tipo="NXM", lleva=2, paga=1)
        self.dos_por_uno.productos.add(self.chicha.producto)

    def vender(self, items, total, **kw):
        return registrar_venta(self.jefe, [{"variante": v.pk, "cantidad": str(q)} for v, q in items],
                               [{"metodo": "YAP", "monto": str(total)}], **kw)

    def test_dos_por_uno_y_devolucion(self):
        v = self.vender([(self.chicha, 3)], "8.00")  # 3 chichas: una gratis
        i = v.items.get()
        self.assertEqual((i.promo, i.promo_descuento, i.subtotal, v.total), (self.dos_por_uno, D("4.00"), D("8.00"), D("8.00")))
        self.assertFalse(Bitacora.objects.filter(accion__in=["venta.precio", "venta.descuento"]).exists())
        d = devolver(v, [{"item": i.pk, "cantidad": "1"}], "FUE", self.jefe, "se derramó")
        self.assertEqual(d.total, D("2.67"))  # se devuelve lo que pagó por una (8 / 3), no el precio de lista

    def test_tres_por_dos_junta_tallas_y_regala_lo_mas_barato(self):
        p = Promocion.objects.create(nombre="3×2 polos", tipo="NXM", lleva=3, paga=2)
        p.productos.add(self.polo)
        v = self.vender([(self.xl, 2), (self.s, 1)], "72.00")  # 36 + 36 + 30: la S sale gratis
        filas = {i.variante_id: i.promo_descuento for i in v.items.all()}
        self.assertEqual((filas[self.s.pk], filas[self.xl.pk]), (D("30.00"), D("0")))

    def test_porcentaje_por_categoria_y_gana_la_mayor(self):
        diez = Promocion.objects.create(nombre="Vuelta al cole", tipo="POR", porcentaje=D("10"))
        diez.categorias.add(self.utiles)
        v = self.vender([(self.cuaderno, 3)], "27.00")
        self.assertEqual(v.items.get().promo, diez)
        mitad = Promocion.objects.create(nombre="Chicha a S/ 3", tipo="PRE", precio=D("3"))
        mitad.productos.add(self.chicha.producto)
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2"}])
        self.assertEqual((lineas[0]["promo"], total), (self.dos_por_uno, D("4.00")))  # 2×1 rebaja 4; a S/ 3 rebaja 2
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "1"}])
        self.assertEqual((lineas[0]["promo"], total), (mitad, D("3.00")))  # con una sola, el 2×1 no rebaja: gana S/ 3

    def test_horario_dias_y_fechas(self):
        p = Promocion(nombre="Happy hour", tipo="POR", porcentaje=D("20"), hora_desde=time(18), hora_hasta=time(20),
                      desde=timezone.localdate() - timedelta(days=30))
        tz = timezone.get_current_timezone()
        lunes = datetime(2026, 11, 23, 19, 0, tzinfo=tz)
        self.assertTrue(p.vigente(lunes))
        self.assertFalse(p.vigente(lunes.replace(hour=20)))
        p.hora_desde, p.hora_hasta = time(22), time(2)  # cruza la medianoche
        self.assertTrue(p.vigente(lunes.replace(hour=23)))
        self.assertTrue(p.vigente(lunes.replace(hour=1)))
        self.assertFalse(p.vigente(lunes.replace(hour=12)))
        p.hora_desde = p.hora_hasta = None
        p.dias = [1]  # solo martes
        self.assertFalse(p.vigente(lunes))
        self.assertTrue(p.vigente(lunes + timedelta(days=1)))
        p.dias, p.hasta = [], lunes.date() - timedelta(days=1)
        self.assertFalse(p.vigente(lunes))
        # en mesas cuenta la hora en que se pidió el plato
        self.dos_por_uno.hora_desde, self.dos_por_uno.hora_hasta = time(18), time(20)
        self.dos_por_uno.save()
        pedido = timezone.localtime().replace(hour=19, minute=0)  # aunque se cobre fuera del horario
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2", "precio": "4", "momento": pedido.isoformat()}],
                                     desde_pedido=True, puede_cambiar_precio=True)
        self.assertEqual(total, D("4.00"))

    def test_no_se_suma_con_precio_especial_ni_precio_a_mano_y_funcion_apagada(self):
        from clientes.models import Cliente

        mayorista = ListaPrecios.objects.create(nombre="Mayorista", porcentaje=D("10"))
        tienda = Cliente.objects.create(nombre="Bodega Luz", lista=mayorista)
        # con el cliente mayorista, 2 chichas: S/ 7.20 a su precio o S/ 4 con el 2×1 → gana el 2×1 (no se suman)
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2"}], cliente_id=tienda.pk)
        self.assertEqual((lineas[0]["regla"], lineas[0]["promo"], lineas[0]["precio"], total), ("", self.dos_por_uno, D("4"), D("4.00")))
        # si el precio especial sale más barato que la promo, se queda con el precio especial
        PrecioEspecial.objects.create(producto=self.chicha.producto, desde=2, precio=D("1.50"))
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2"}])
        self.assertEqual((lineas[0]["regla"], lineas[0]["promo"], total), ("Precio por cantidad", None, D("3.00")))
        PrecioEspecial.objects.all().delete()
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2", "precio": "3.80"}], puede_cambiar_precio=True)
        self.assertIsNone(lineas[0]["promo"])
        Ajustes.objects.filter(pk=1).update(funciones_inactivas=["promociones"])
        lineas, total = armar_lineas([{"variante": self.chicha.pk, "cantidad": "2"}])
        self.assertEqual(total, D("8.00"))

    def test_pantallas(self):
        self.client.force_login(self.jefe)
        r = self.client.post(reverse("productos:promocion_nueva"), {
            "nombre": "Martes de cuadernos", "tipo": "POR", "porcentaje": "15", "categorias": [self.utiles.pk],
            "desde": timezone.localdate().isoformat(), "dias": ["1"], "activa": "on"})
        self.assertRedirects(r, reverse("productos:promociones"))
        p = Promocion.objects.get(nombre="Martes de cuadernos")
        self.assertEqual(p.dias, [1])
        self.assertTrue(Bitacora.objects.filter(accion="promocion.cambio").exists())
        r = self.client.post(reverse("productos:promocion_nueva"), {"nombre": "Mal", "tipo": "NXM", "lleva": "1", "paga": "1",
                                                                    "desde": timezone.localdate().isoformat()})
        self.assertContains(r, "lleva tiene que ser mayor")
        self.assertContains(self.client.get(reverse("productos:promociones")), "Martes de cuadernos")
        # Vender pide el precio al servidor: la cotización trae la promo
        self.assertContains(self.client.get(reverse("ventas:pos")), "var COTIZA = true")
        r = self.client.post(reverse("ventas:cotizar"), {"items": [{"variante": self.chicha.pk, "cantidad": "2"}]},
                             content_type="application/json")
        self.assertEqual((r.json()["subtotal"], r.json()["lineas"][0]["desc"]), ("4.00", "4.00"))
        v = self.vender([(self.chicha, 2)], "4.00")
        self.assertContains(self.client.get(reverse("ventas:ticket", args=[v.pk])), "PROMO 2×1")
        self.assertContains(self.client.get(reverse("reportes:inicio")), "2×1 chicha")
