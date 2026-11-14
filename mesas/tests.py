import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, generar_variantes, mover_stock

from .models import Cuenta, Mesa, Zona
from .servicios import MesaError, abrir_cuenta, agregar, anular_cuenta, cambiar_cantidad, cobrar, enviar_cocina, juntar, mover, quitar

D = Decimal


class MesasTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "propina_activa": True})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        abrir(self.cajero, D("50"))
        z = Zona.objects.create(nombre="Salón")
        self.m1 = Mesa.objects.create(zona=z, nombre="1")
        self.m2 = Mesa.objects.create(zona=z, nombre="2")
        lomo = Producto.objects.create(nombre="Lomo saltado", precio=D("22"), maneja_stock=False)
        self.lomo = asegurar_variante_unica(lomo)
        gaseosa = Producto.objects.create(nombre="Inca Kola", precio=D("4"))
        self.gas = asegurar_variante_unica(gaseosa)
        mover_stock(self.gas, 10, MovimientoStock.Tipo.INGRESO)

    def test_flujo_completo(self):
        c = abrir_cuenta(self.mozo, self.m1, 3)
        with self.assertRaises(MesaError):
            abrir_cuenta(self.mozo, self.m1, 2)
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 2, "nota": "sin cebolla"}, {"variante": self.gas.pk, "cantidad": 1}], self.mozo)
        agregar(c, [{"variante": self.lomo.pk, "cantidad": 1, "nota": "sin cebolla"}], self.mozo)  # se suma al mismo
        self.assertEqual(c.items.get(variante=self.lomo).cantidad, D("3"))
        self.assertIsNotNone(enviar_cocina(c))
        self.assertIsNone(enviar_cocina(c))
        item = c.items.get(variante=self.gas)
        with self.assertRaises(MesaError):
            cambiar_cantidad(item, 1)
        with self.assertRaisesMessage(MesaError, "solo alguien con permiso"):
            quitar(item, self.mozo, "x", puede_anular=False)
        quitar(item, self.jefe, "se equivocó", puede_anular=True)
        self.assertEqual(c.total_por_cobrar, D("66"))
        # dividir: primero solo una parte
        agregar(c, [{"variante": self.gas.pk, "cantidad": 2}], self.mozo)
        gas = c.items.get(variante=self.gas, anulado=False)
        v1 = cobrar(c, self.cajero, [{"metodo": "YAP", "monto": "8"}], item_ids=[gas.pk])
        c.refresh_from_db()
        self.assertTrue(c.abierta)
        self.gas.refresh_from_db()
        self.assertEqual(self.gas.stock, D("8"))  # el stock baja al cobrar
        v2 = cobrar(c, self.cajero, [{"metodo": "EFE", "monto": "100"}], propina="6")
        c.refresh_from_db()
        self.assertEqual(c.estado, Cuenta.Estado.COBRADA)
        self.assertEqual((v2.total, v2.propina, v2.vuelto, v2.atendio, v1.atendio), (D("66"), D("6"), D("28"), self.mozo, self.mozo))
        self.assertEqual(v2.pagos.get().monto, D("72"))
        self.assertIsNotNone(abrir_cuenta(self.mozo, self.m1, 2))  # mesa libre de nuevo
        with self.assertRaises(MesaError):
            cobrar(c, self.cajero, [])

    def test_mover_juntar_anular(self):
        a = abrir_cuenta(self.mozo, self.m1, 2)
        agregar(a, [{"variante": self.lomo.pk, "cantidad": 1}], self.mozo)
        b = abrir_cuenta(self.mozo, self.m2, 2)
        with self.assertRaises(MesaError):
            mover(a, self.m2)
        juntar(a, b)
        a.refresh_from_db()
        self.assertEqual((a.estado, b.items.count(), b.personas), (Cuenta.Estado.ANULADA, 1, 4))
        mover(b, self.m1)
        enviar_cocina(b)
        with self.assertRaises(MesaError):
            anular_cuenta(b, self.mozo, "", puede_anular=False)
        anular_cuenta(b, self.jefe, "se fueron", puede_anular=True)
        vacia = abrir_cuenta(self.mozo, self.m2, 1)
        anular_cuenta(vacia, self.mozo)  # sin consumo: se libera sin permiso

    def test_vistas(self):
        self.client.force_login(self.mozo)
        self.assertEqual(self.client.get(reverse("mesas:mapa")).status_code, 200)
        r = self.client.post(reverse("mesas:abrir"), {"mesa": self.m1.pk, "personas": 2})
        c = Cuenta.objects.get()
        self.assertRedirects(r, reverse("mesas:agregar", args=[c.pk]))
        self.assertContains(self.client.get(reverse("mesas:agregar", args=[c.pk])), "Lomo saltado")
        r = self.client.post(reverse("mesas:agregar", args=[c.pk]), json.dumps({"enviar": True, "items": [{"variante": self.lomo.pk, "cantidad": 2, "nota": "sin ají"}]}),
                             content_type="application/json")
        r = self.client.get(r.json()["url"])
        self.assertContains(r, "Díctale a cocina")
        self.assertContains(r, "sin ají")
        self.assertContains(self.client.get(reverse("mesas:mapa"), HTTP_HX_REQUEST="true"), "S/ 44.00")
        for url in ("mesas:precuenta", "mesas:comanda", "mesas:cambiar"):
            self.assertEqual(self.client.get(reverse(url, args=[c.pk])).status_code, 200)
        # el mozo no cobra
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), "{}", content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps({"pagos": [{"metodo": "EFE", "monto": "50"}], "token": "x1"}),
                             content_type="application/json")
        self.assertIn("volver=/mesas/", r.json()["url"])
        c.refresh_from_db()
        self.assertEqual(c.estado, Cuenta.Estado.COBRADA)
        self.assertContains(self.client.get(r.json()["url"]), "Volver a las mesas")

    def test_configurar(self):
        self.client.force_login(self.jefe)
        z = Zona.objects.get()
        self.client.post(reverse("mesas:configurar"), {"accion": "lote", "zona": z.pk, "prefijo": "T", "desde": 1, "hasta": 3, "capacidad": 2})
        self.assertEqual(Mesa.objects.filter(nombre__startswith="T").count(), 3)
        self.client.force_login(self.mozo)
        self.assertEqual(self.client.get(reverse("mesas:configurar")).status_code, 403)

    def test_modulo_apagado(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["mesas"])
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(reverse("mesas:mapa")).status_code, 403)


class CocinaEImpresionTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "cocina_pantalla": True, "ticket_ancho": 58})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.chef = User.objects.create_user("chef", password="x-clave-123")
        self.chef.groups.add(Group.objects.get(name="Cocina"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        p = Producto.objects.create(nombre="Ceviche", precio=D("30"), maneja_stock=False)
        self.v = asegurar_variante_unica(p)
        self.c = abrir_cuenta(self.mozo, self.mesa, 2)
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 2, "nota": "poco picante"}], self.mozo)
        self.ts = enviar_cocina(self.c)

    def test_rol_cocina(self):
        self.client.force_login(self.chef)
        self.assertRedirects(self.client.get(reverse("core:inicio")), reverse("mesas:cocina"))
        r = self.client.get(reverse("mesas:cocina"))
        self.assertContains(r, "poco picante")
        self.assertContains(r, "Mesa 1")
        self.assertEqual(self.client.get(reverse("mesas:mapa")).status_code, 403)
        self.client.force_login(self.mozo)
        self.assertEqual(self.client.get(reverse("mesas:cocina")).status_code, 403)

    def test_listo_y_servido(self):
        self.client.force_login(self.chef)
        self.client.post(reverse("mesas:cocina_marcar"), {"cuenta": self.c.pk, "enviado": self.ts.isoformat()})
        item = self.c.items.get()
        self.assertIsNotNone(item.listo_en)
        r = self.client.get(reverse("mesas:cocina"))
        self.assertEqual(r.context["pendientes"], [])
        self.assertEqual(len(r.context["listas"]), 1)
        self.client.post(reverse("mesas:cocina_marcar"), {"cuenta": self.c.pk, "enviado": self.ts.isoformat(), "listo": "0"})
        item.refresh_from_db()
        self.assertIsNone(item.listo_en)
        self.client.post(reverse("mesas:cocina_marcar"), {"item": item.pk})  # un plato: alterna
        item.refresh_from_db()
        self.assertIsNotNone(item.listo_en)
        self.client.force_login(self.mozo)
        self.assertContains(self.client.get(reverse("mesas:mapa"), HTTP_HX_REQUEST="true"), "bi-bell-fill")
        self.assertContains(self.client.get(reverse("mesas:cuenta", args=[self.c.pk])), "Ya serví lo listo")
        self.client.post(reverse("mesas:servido", args=[self.c.pk]))
        item.refresh_from_db()
        self.assertIsNotNone(item.servido_en)

    def test_impresiones(self):
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("mesas:comanda", args=[self.c.pk]) + "?enviado=" + self.ts.isoformat().replace("+", "%2B"))
        self.assertContains(r, "POCO PICANTE")
        self.assertContains(r, "58mm")  # ancho configurado
        self.assertContains(self.client.get(reverse("mesas:precuenta", args=[self.c.pk])), "PRECUENTA")
        abrir(self.cajero, D("0"))
        v = cobrar(self.c, self.cajero, [{"metodo": "EFE", "monto": "60"}])
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("ventas:imprimir", args=[v.pk]))
        self.assertContains(r, "NOTA DE VENTA N° " + v.numero_str)
        self.assertContains(r, "Mozo: mozo")
        r = self.client.get(reverse("caja:imprimir", args=[v.sesion_caja_id]))
        self.assertContains(r, "CORTE DE CAJA (PARCIAL)")
        self.client.force_login(self.mozo)  # el ticket de otro no
        self.assertEqual(self.client.get(reverse("ventas:imprimir", args=[v.pk])).status_code, 403)


class CasosBordeTests(TestCase):
    """Situaciones entre módulos que no deben trabar el trabajo."""

    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": []})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        abrir(self.jefe, D("0"))
        z = Zona.objects.create(nombre="Salón")
        self.mesa = Mesa.objects.create(zona=z, nombre="1")
        self.prod = Producto.objects.create(nombre="Lomo", precio=D("20"), maneja_stock=False)
        self.v = asegurar_variante_unica(self.prod)
        self.c = abrir_cuenta(self.mozo, self.mesa)
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 2}], self.mozo)

    def test_producto_desactivado_y_precio_cambiado_se_cobra_igual(self):
        self.prod.activo = False
        self.prod.precio = D("25")
        self.prod.save()
        venta = cobrar(self.c, self.jefe, [{"metodo": "EFE", "monto": "40"}])
        self.assertEqual(venta.total, D("40"))  # el precio que tenía al pedirlo
        self.assertFalse(venta.items.get().precio_cambiado)

    def test_anular_cobro_reabre_la_mesa(self):
        from ventas.servicios import anular_venta

        venta = cobrar(self.c, self.jefe, [{"metodo": "TAR", "monto": "40"}])
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, Cuenta.Estado.COBRADA)
        v = anular_venta(venta, self.jefe, "era Yape, no tarjeta")
        self.assertEqual(v.cuenta_reabierta, self.c)
        self.c.refresh_from_db()
        self.assertEqual((self.c.estado, self.c.total_por_cobrar), (Cuenta.Estado.ABIERTA, D("40")))
        venta2 = cobrar(self.c, self.jefe, [{"metodo": "YAP", "monto": "40"}])
        self.assertEqual(venta2.total, D("40"))
        # si la mesa ya tiene otros clientes, la cuenta reabierta queda aparte
        nueva = abrir_cuenta(self.mozo, self.mesa)
        v = anular_venta(venta2, self.jefe, "otra vez")
        self.assertIsNone(v.cuenta_reabierta.mesa)
        self.assertIn("cobro anulado", v.cuenta_reabierta.titulo)
        self.assertTrue(nueva.abierta)

    def test_variante_pedida_no_se_borra(self):
        self.client.force_login(self.jefe)
        self.client.post(reverse("productos:variante_eliminar", args=[self.v.pk]))  # única con pedido: no hay error
        p2 = Producto.objects.create(nombre="Chicha", precio=D("5"), maneja_stock=False)
        generar_variantes(p2, "Vaso, Jarra")
        vaso = p2.variantes.get(nombre="Vaso")
        agregar(self.c, [{"variante": vaso.pk, "cantidad": 1}], self.mozo)
        r = self.client.post(reverse("productos:variante_eliminar", args=[vaso.pk]))
        self.assertEqual(r.status_code, 302)
        vaso.refresh_from_db()
        self.assertFalse(vaso.activa)

    def test_redirecciones_externas_bloqueadas(self):
        from caja.models import SesionCaja

        SesionCaja.objects.all().delete()
        self.client.force_login(self.jefe)
        r = self.client.post("/caja/?next=//sitio-falso.com", {"monto_inicial": "10"})
        self.assertEqual(r["Location"], reverse("caja:mi_caja"))
        venta = cobrar(self.c, self.jefe, [{"metodo": "EFE", "monto": "40"}])
        r = self.client.get(reverse("ventas:ticket", args=[venta.pk]) + "?nueva=1&volver=//sitio-falso.com")
        self.assertNotContains(r, "sitio-falso")
