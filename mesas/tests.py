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
from .servicios import MesaError, cuenta_de_mesa, separar_mesa, unir_mesas, abrir_cuenta, agregar, anular_cuenta, cambiar_cantidad, cobrar, enviar_cocina, juntar, mover, quitar

D = Decimal


class MesasTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"], "propina_activa": True})  # sin pantalla de cocina: se dicta
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

    def test_mesas_juntas(self):
        m3 = Mesa.objects.create(zona=self.m1.zona, nombre="3")
        m4 = Mesa.objects.create(zona=self.m1.zona, nombre="4")
        fam = abrir_cuenta(self.mozo, self.m1, 8)
        unir_mesas(fam, [self.m2, m3])
        self.assertEqual(Cuenta.objects.get(pk=fam.pk).titulo, "Mesa 1 + 2 + 3")
        # Una mesa pegada no se puede abrir ni volver a juntar con otra cuenta
        with self.assertRaises(MesaError):
            abrir_cuenta(self.mozo, self.m2, 2)
        otra = abrir_cuenta(self.mozo, m4, 2)
        with self.assertRaises(MesaError):
            unir_mesas(otra, [m3])
        with self.assertRaises(MesaError):
            mover(otra, self.m2)
        self.assertEqual(cuenta_de_mesa(m3).pk, fam.pk)
        # Separar devuelve la mesa
        separar_mesa(fam, m3)
        self.assertIsNone(cuenta_de_mesa(Mesa.objects.get(pk=m3.pk)))
        # Juntar dos cuentas: la mesa de origen queda pegada a la otra (no libre)
        agregar(otra, [{"variante": self.lomo.pk, "cantidad": 1}], self.mozo)
        juntar(otra, fam)
        self.assertEqual(cuenta_de_mesa(Mesa.objects.get(pk=m4.pk)).pk, fam.pk)
        self.assertEqual(Cuenta.objects.get(pk=fam.pk).titulo, "Mesa 1 + 2 + 4")
        # El mapa las muestra ocupadas y enlazadas a la misma cuenta
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("mesas:mapa"))
        self.assertContains(r, "con la 1", count=2)
        # Al cerrar la cuenta se liberan todas
        anular_cuenta(fam, self.jefe, "prueba", puede_anular=True)
        for m in (self.m1, self.m2, m4):
            self.assertIsNone(cuenta_de_mesa(Mesa.objects.get(pk=m.pk)))
        self.assertIsNotNone(abrir_cuenta(self.mozo, self.m2, 2))

    def test_personas_editables(self):
        self.client.force_login(self.mozo)
        self.client.post(reverse("mesas:abrir"), {"mesa": self.m1.pk, "personas": 5})
        c = Cuenta.objects.get(mesa=self.m1, estado=Cuenta.Estado.ABIERTA)
        self.assertEqual(c.personas, 5)
        self.assertContains(self.client.get(reverse("mesas:cuenta", args=[c.pk])), "m-personas")
        self.client.post(reverse("mesas:personas", args=[c.pk]), {"personas": 3})
        c.refresh_from_db()
        self.assertEqual(c.personas, 3)
        self.client.post(reverse("mesas:personas", args=[c.pk]), {"personas": 0})
        c.refresh_from_db()
        self.assertEqual(c.personas, 0)  # sin indicar
        self.assertContains(self.client.get(reverse("mesas:cuenta", args=[c.pk])), "sin indicar")
        self.client.post(reverse("mesas:personas", args=[c.pk]), {"personas": 3})
        self.client.post(reverse("mesas:personas", args=[c.pk]), {"personas": 500})
        c.refresh_from_db()
        self.assertEqual(c.personas, 3)

    def test_vista_juntar_al_abrir(self):
        self.client.force_login(self.mozo)
        r = self.client.post(reverse("mesas:abrir"), {"mesa": self.m1.pk, "personas": 6, "juntar": "1"})
        c = Cuenta.objects.get(mesa=self.m1, estado=Cuenta.Estado.ABIERTA)
        self.assertRedirects(r, reverse("mesas:cambiar", args=[c.pk]) + "?nueva=1", fetch_redirect_response=False)
        self.assertContains(self.client.get(r.url), "Juntar mesas")
        r = self.client.post(reverse("mesas:cambiar", args=[c.pk]), {"accion": "unir", "mesas": [self.m2.pk], "nueva": "1"})
        self.assertRedirects(r, reverse("mesas:agregar", args=[c.pk]), fetch_redirect_response=False)
        self.assertEqual(Mesa.objects.get(pk=self.m2.pk).unida_a_id, c.pk)
        # Tocar la mesa pegada lleva a la misma cuenta
        r = self.client.post(reverse("mesas:abrir"), {"mesa": self.m2.pk, "personas": 2})
        self.assertRedirects(r, reverse("mesas:cuenta", args=[c.pk]), fetch_redirect_response=False)

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

    def test_cocina_barra_y_mozo(self):
        from productos.models import Categoria

        Ajustes.objects.filter(pk=1).update(modulos_inactivos=[])
        platos = Categoria.objects.create(nombre="Platos de fondo")
        bebidas = Categoria.objects.create(nombre="Bebidas", area="MOZ")
        tragos = Categoria.objects.create(nombre="Jugos y tragos", area="BAR")
        Producto.objects.filter(pk=self.lomo.producto_id).update(categoria=platos)
        Producto.objects.filter(pk=self.gas.producto_id).update(categoria=bebidas)
        pisco = asegurar_variante_unica(Producto.objects.create(nombre="Pisco sour", precio=D("18"), maneja_stock=False, categoria=tragos))
        # Un producto puede ir a otro lado que su categoría
        cafe = asegurar_variante_unica(Producto.objects.create(nombre="Café", precio=D("5"), maneja_stock=False, categoria=bebidas, area="BAR"))
        c = abrir_cuenta(self.mozo, self.m1, 2)
        agregar(c, [{"variante": v.pk, "cantidad": 1} for v in (self.lomo, self.gas, pisco, cafe)], self.mozo)
        self.assertEqual(sorted(c.items.values_list("area", flat=True)), ["BAR", "BAR", "COC", "MOZ"])
        enviar_cocina(c)
        gas = c.items.get(variante=self.gas)
        self.assertIsNotNone(gas.listo_en)  # lo lleva el mozo: listo al instante
        self.assertIsNone(c.items.get(variante=self.lomo).listo_en)
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("mesas:cocina"))
        self.assertContains(r, "Lomo saltado")
        self.assertNotContains(r, "Inca Kola")
        self.assertNotContains(r, "Pisco sour")
        self.assertContains(r, "Barra")  # hay barra: aparecen las pestañas
        r = self.client.get(reverse("mesas:cocina") + "?area=BAR")
        self.assertContains(r, "Pisco sour")
        self.assertContains(r, "Café")
        self.assertNotContains(r, "Lomo saltado")
        # La comanda de barra solo trae lo de barra
        r = self.client.get(reverse("mesas:comanda", args=[c.pk]) + "?area=BAR")
        self.assertContains(r, "BARRA")
        self.assertNotContains(r, "Lomo saltado")
        # "Todo listo" en la barra no toca la cocina
        ts = c.items.get(variante=pisco).enviado_en
        self.client.post(reverse("mesas:cocina_marcar"), {"cuenta": c.pk, "enviado": ts.isoformat(), "area": "BAR"})
        self.assertIsNotNone(c.items.get(variante=pisco).listo_en)
        self.assertIsNone(c.items.get(variante=self.lomo).listo_en)

    def test_guardar_zona_completa(self):
        self.client.force_login(self.jefe)
        z = Zona.objects.get()
        url = reverse("mesas:configurar")
        self.client.post(url, {"accion": "lote", "zona": z.pk, "prefijo": "T", "desde": 1, "hasta": 3, "capacidad": 2})
        terraza = Zona.objects.create(nombre="Terraza", orden=20)
        t1, t2, t3 = (Mesa.objects.get(nombre=n) for n in ("T1", "T2", "T3"))
        datos = {"accion": "guardar_zona", "pk": z.pk}
        for m in z.mesas.all():
            datos.update({f"nombre_{m.pk}": m.nombre, f"capacidad_{m.pk}": m.capacidad, f"zona_{m.pk}": m.zona_id, f"activa_{m.pk}": "on"})
        # Varias a la vez: se intercambian T1 y T2, T3 cambia capacidad y pasa a Terraza
        datos.update({f"nombre_{t1.pk}": "T2", f"nombre_{t2.pk}": "T1", f"capacidad_{t3.pk}": 6, f"zona_{t3.pk}": terraza.pk})
        r = self.client.post(url, datos)
        self.assertEqual(r.status_code, 302)
        t1.refresh_from_db(); t2.refresh_from_db(); t3.refresh_from_db()
        self.assertEqual((t1.nombre, t2.nombre), ("T2", "T1"))
        self.assertEqual((t3.capacidad, t3.zona_id), (6, terraza.pk))
        # Nombre repetido: no se guarda nada y se vuelve a mostrar lo escrito
        datos = {"accion": "guardar_zona", "pk": z.pk}
        for m in z.mesas.all():
            datos.update({f"nombre_{m.pk}": m.nombre, f"capacidad_{m.pk}": 9, f"zona_{m.pk}": z.pk, f"activa_{m.pk}": "on"})
        datos[f"nombre_{t1.pk}"] = "T1"
        r = self.client.post(url, datos)
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "No se guardó nada", status_code=400)
        self.assertContains(r, 'value="9"', status_code=400)
        t2.refresh_from_db()
        self.assertEqual(t2.capacidad, 2)
        # Quitar una mesa guarda también los demás cambios
        datos = {"accion": "guardar_zona", "pk": z.pk, "borrar": t1.pk}
        for m in z.mesas.all():
            datos.update({f"nombre_{m.pk}": m.nombre, f"capacidad_{m.pk}": 5, f"zona_{m.pk}": z.pk, f"activa_{m.pk}": "on"})
        self.client.post(url, datos)
        self.assertFalse(Mesa.objects.filter(pk=t1.pk).exists())
        t2.refresh_from_db()
        self.assertEqual(t2.capacidad, 5)

    def test_modulo_apagado(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["mesas"])
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(reverse("mesas:mapa")).status_code, 403)


class CocinaEImpresionTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "ticket_ancho": 58})
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


class CortesiasYDescuentosTests(TestCase):
    """Platos de la casa y descuentos al cobrar: siempre con motivo y con alguien que lo autorice."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": []})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="jefe-clave-123", first_name="Ana")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        abrir(self.cajero, D("0"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("20"), maneja_stock=False))
        self.c = abrir_cuenta(self.mozo, self.mesa)
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 3}], self.mozo)
        self.item = self.c.items.get()
        self.url = reverse("mesas:cortesia", args=[self.item.pk])

    def test_mozo_necesita_clave_de_supervisor(self):
        self.client.force_login(self.mozo)
        self.client.post(self.url, {"motivo": "Demora", "cantidad": "1"})
        self.item.refresh_from_db()
        self.assertFalse(self.item.cortesia)
        # clave equivocada o usuario sin permiso: no pasa
        self.client.post(self.url, {"motivo": "Demora", "cantidad": "1", "sup_usuario": "jefe", "sup_clave": "mala"})
        self.client.post(self.url, {"motivo": "Demora", "cantidad": "1", "sup_usuario": "cajero", "sup_clave": "x-clave-123"})
        self.assertEqual(self.c.items.filter(cortesia=True).count(), 0)
        # el supervisor autoriza una de las tres unidades
        self.client.post(self.url, {"motivo": "Demora", "cantidad": "1", "sup_usuario": "JEFE", "sup_clave": "jefe-clave-123"})
        regalo = self.c.items.get(cortesia=True)
        self.assertEqual((regalo.cantidad, regalo.cortesia_por, regalo.subtotal, regalo.cortesia_motivo), (D("1"), self.jefe, D("0"), "Demora"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.cantidad, D("2"))
        self.assertEqual(self.c.total_por_cobrar, D("40"))
        # lo nuevo que se pide no se mezcla con la línea de cortesía
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 1}], self.mozo)
        self.assertEqual(self.c.items.get(cortesia=True).cantidad, D("1"))
        # al cobrar, la cortesía queda en la venta a 0 con su precio de lista
        venta = cobrar(self.c, self.cajero, [{"metodo": "EFE", "monto": "60"}])
        it = venta.items.get(cortesia=True)
        self.assertEqual((venta.total, it.importe if hasattr(it, "importe") else it.subtotal, it.precio_lista, it.cortesia_por),
                         (D("60"), D("0"), D("20"), self.jefe))
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("ventas:ticket", args=[venta.pk]))
        self.assertContains(r, "CORTESÍA")
        r = self.client.get(reverse("reportes:inicio") + "?p=hoy")
        self.assertEqual(r.context["rebajas"]["valor_cortesias"], D("20.00"))
        self.assertContains(r, "Demora")
        self.assertEqual(self.client.get(reverse("reportes:inicio") + "?p=hoy&excel=1").status_code, 200)

    def test_bloqueo_tras_varios_intentos(self):
        self.client.force_login(self.mozo)
        for _ in range(5):
            self.client.post(self.url, {"motivo": "Demora", "sup_usuario": "jefe", "sup_clave": "mala"})
        self.client.post(self.url, {"motivo": "Demora", "sup_usuario": "jefe", "sup_clave": "jefe-clave-123"})
        self.assertFalse(self.c.items.filter(cortesia=True).exists())

    def test_quien_tiene_permiso_no_necesita_clave_y_puede_quitarla(self):
        self.client.force_login(self.jefe)
        self.client.post(self.url, {"motivo": "Cumpleaños"})
        self.item.refresh_from_db()
        self.assertEqual((self.item.cortesia, self.item.cantidad, self.c.total_por_cobrar), (True, D("3"), D("0")))
        self.client.post(self.url, {"motivo": "", "quitar": "1"})
        self.item.refresh_from_db()
        self.assertFalse(self.item.cortesia)
        # sin motivo no hay cortesía; cantidad absurda tampoco
        self.client.post(self.url, {"motivo": ""})
        self.client.post(self.url, {"motivo": "x", "cantidad": "abc"})
        self.client.post(self.url, {"motivo": "x", "cantidad": "9"})
        self.assertFalse(self.c.items.filter(cortesia=True).exists())

    def _cobrar(self, usuario, **extra):
        self.client.force_login(usuario)
        datos = {"pagos": [{"metodo": "EFE", "monto": "60"}], **extra}
        return self.client.post(reverse("mesas:cobrar", args=[self.c.pk]), json.dumps(datos), content_type="application/json")

    def test_descuento_al_cobrar(self):
        r = self._cobrar(self.cajero, descuento="10")
        self.assertContains(r, "motivo", status_code=400)
        r = self._cobrar(self.cajero, descuento="10", descuento_motivo="Cliente frecuente")
        self.assertContains(r, "Necesita autorizaci", status_code=400)
        r = self._cobrar(self.cajero, descuento="10", descuento_motivo="Cliente frecuente", sup_usuario="jefe", sup_clave="jefe-clave-123")
        self.assertEqual(r.status_code, 200, r.content)
        from ventas.models import Venta

        v = Venta.objects.get()
        self.assertEqual((v.total, v.descuento, v.descuento_motivo, v.descuento_por, v.usuario), (D("50"), D("10"), "Cliente frecuente", self.jefe, self.cajero))
        self.client.force_login(self.jefe)
        r = self.client.get(reverse("reportes:inicio") + "?p=hoy")
        self.assertEqual(r.context["rebajas"]["valor_descuentos"], D("10.00"))
        self.assertContains(self.client.get(reverse("ventas:ticket", args=[v.pk])), "Cliente frecuente")

    def test_cuenta_muestra_boton_y_modal(self):
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("mesas:cuenta", args=[self.c.pk]))
        self.assertContains(r, 'id="m-cortesia"')
        self.assertContains(r, 'name="sup_clave"')
        self.client.force_login(self.jefe)
        self.assertNotContains(self.client.get(reverse("mesas:cuenta", args=[self.c.pk])), 'name="sup_clave"')


class PagarAntesOAlFinalTests(TestCase):
    """Se puede pagar antes, al final, o pagar y seguir pidiendo; la mesa se libera cuando se van."""

    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": []})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("0"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("20"), maneja_stock=False))
        self.c = abrir_cuenta(self.mozo, self.mesa)

    def _cobrar_web(self, **extra):
        self.client.force_login(self.cajero)
        datos = {"pagos": [{"metodo": "EFE", "monto": "100"}], **extra}
        return self.client.post(reverse("mesas:cobrar", args=[self.c.pk]), json.dumps(datos), content_type="application/json")

    def test_pagar_antes_envia_a_cocina_y_la_mesa_queda_pagada(self):
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 2}], self.mozo)  # anotado, sin enviar
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("mesas:cuenta", args=[self.c.pk]))
        self.assertFalse(r.context["liberar_al_cobrar"])  # algo no salió de cocina: por defecto no se libera
        r = self._cobrar_web(liberar=False)
        self.assertEqual(r.status_code, 200, r.content)
        self.c.refresh_from_db()
        self.assertTrue(self.c.abierta)
        self.assertTrue(self.c.pagada())
        item = self.c.items.get()
        self.assertIsNotNone(item.enviado_en)  # se mandó a cocina al cobrar
        self.assertIn("enviado%3D", r.json()["url"])  # al volver, la cuenta muestra qué dictar / la comanda
        # cocina lo ve, lo marca listo; el mapa lo muestra como pagada con su aviso
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("mesas:mapa"))
        self.assertContains(r, "mesa pagada")  # clase del cuadro de la mesa
        r = self.client.get(reverse("mesas:cuenta", args=[self.c.pk]))
        self.assertContains(r, "Ya pagado")
        self.assertContains(r, reverse("mesas:liberar", args=[self.c.pk]))
        # sirven y siguen comiendo: la mesa NO se libera sola
        ItemCuenta = item.__class__
        ItemCuenta.objects.filter(pk=item.pk).update(listo_en=item.enviado_en)
        self.client.post(reverse("mesas:servido", args=[self.c.pk]))
        self.c.refresh_from_db()
        self.assertTrue(self.c.abierta)
        # se van: el mozo libera
        self.client.post(reverse("mesas:liberar", args=[self.c.pk]))
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, Cuenta.Estado.COBRADA)
        self.assertIsNotNone(abrir_cuenta(self.mozo, self.mesa))

    def test_pagar_y_volver_a_pedir_es_la_misma_cuenta(self):
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 1}], self.mozo)
        enviar_cocina(self.c)
        v1 = cobrar(self.c, self.cajero, [{"metodo": "EFE", "monto": "20"}], liberar=False)
        with self.assertRaises(MesaError):  # la mesa sigue ocupada por ellos
            abrir_cuenta(self.mozo, self.mesa)
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 1}], self.mozo)
        self.assertEqual(self.c.total_por_cobrar, D("20"))  # solo lo nuevo
        self.assertFalse(self.c.pagada())
        with self.assertRaises(MesaError):  # no se libera con algo por cobrar
            from .servicios import liberar_mesa
            liberar_mesa(self.c)
        v2 = cobrar(self.c, self.cajero, [{"metodo": "YAP", "monto": "20"}])
        self.assertNotEqual(v1.pk, v2.pk)
        self.assertEqual((v1.total, v2.total), (D("20"), D("20")))
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, Cuenta.Estado.COBRADA)  # pagaron al final y se fueron

    def test_pagar_al_final_libera_como_siempre(self):
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 1}], self.mozo)
        enviar_cocina(self.c)
        self.c.items.update(listo_en=self.c.items.get().enviado_en)
        self.client.force_login(self.cajero)
        self.assertTrue(self.client.get(reverse("mesas:cuenta", args=[self.c.pk])).context["liberar_al_cobrar"])
        r = self._cobrar_web()
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, Cuenta.Estado.COBRADA)
        self.assertIn("volver=/mesas/", r.json()["url"])

    def test_anular_el_cobro_de_una_mesa_pagada_vuelve_a_cobrarse(self):
        from ventas.servicios import anular_venta

        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        agregar(self.c, [{"variante": self.v.pk, "cantidad": 2}], self.mozo)
        venta = cobrar(self.c, self.cajero, [{"metodo": "EFE", "monto": "40"}], liberar=False)
        anular_venta(venta, jefe, "el cliente se fue sin su comida")
        self.c.refresh_from_db()
        self.assertTrue(self.c.abierta)
        self.assertEqual(self.c.total_por_cobrar, D("40"))
        quitar(self.c.items.get(), jefe, "Cliente se fue, demora", puede_anular=True)
        anular_cuenta(self.c, jefe, "Cliente se fue", puede_anular=True)
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, Cuenta.Estado.ANULADA)


class PartesIgualesTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": []})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("0"))
        self.mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        v = asegurar_variante_unica(Producto.objects.create(nombre="Lomo", precio=D("50"), maneja_stock=False))
        self.c = abrir_cuenta(self.cajero, self.mesa, 3)
        agregar(self.c, [{"variante": v.pk, "cantidad": 2}], self.cajero)

    def test_tres_personas_pagan_cada_una_a_su_manera(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("mesas:precuenta", args=[self.c.pk]))
        self.assertContains(r, "Entre 3 personas")
        self.assertContains(r, "33.33 c/u")
        # 100 entre 3: 33.30 + 33.30 + 33.40; una paga con Yape, una con tarjeta y otra en efectivo con 50
        datos = {"pagos": [{"metodo": "YAP", "monto": "33.30"}, {"metodo": "TAR", "monto": "33.30"}, {"metodo": "EFE", "monto": "50.00"}],
                 "partes": 3}
        r = self.client.post(reverse("mesas:cobrar", args=[self.c.pk]), json.dumps(datos), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        from ventas.models import Venta

        v = Venta.objects.get()
        self.assertEqual((v.total, v.vuelto), (D("100"), D("16.60")))
        self.assertEqual(sorted((p.metodo, p.monto) for p in v.pagos.all()), [("EFE", D("33.40")), ("TAR", D("33.30")), ("YAP", D("33.30"))])
        self.assertEqual(v.nota, "Mesa 1 · pagado en 3 partes iguales")


class DeliveryTests(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [],
                                                        "delivery_costo": D("5")})
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("0"))
        self.v = asegurar_variante_unica(Producto.objects.create(nombre="Pollo entero", precio=D("60"), maneja_stock=False))

    def _nuevo(self, **extra):
        self.client.force_login(self.mozo)
        datos = {"telefono": "987 111 222", "nombre": "Rosa", "direccion": "Av. Grau 120", "referencia": "puerta verde", "paga_con": "100", **extra}
        self.client.post(reverse("mesas:delivery_nuevo"), datos)
        return Cuenta.objects.filter(tipo=Cuenta.Tipo.DELIVERY).latest("pk")

    def test_flujo_pago_contra_entrega(self):
        from clientes.models import Cliente

        c = self._nuevo()
        self.assertEqual((c.telefono, c.costo_envio, c.estado_envio, c.titulo), ("987111222", D("5.00"), "PRE", f"Delivery #{c.pk} · Rosa"))
        self.assertEqual(Cliente.objects.get().telefono, "987111222")  # se recuerda para la próxima
        agregar(c, [{"variante": self.v.pk}], self.mozo)
        enviar_cocina(c)
        self.assertEqual(c.total_por_cobrar, D("65"))  # pollo + envío
        self.assertEqual(c.vuelto_para, D("35"))
        # la cocina no ve el envío
        from .views import _comandas

        self.assertEqual([i.descripcion for comanda in _comandas()["pendientes"] for i in comanda["items"]], ["Pollo entero"])
        # mapa, cuenta y hoja del repartidor
        self.assertContains(self.client.get(reverse("mesas:mapa")), "Av. Grau 120")
        r = self.client.get(reverse("mesas:precuenta", args=[c.pk]))
        self.assertContains(r, "DELIVERY #")
        self.assertContains(r, "vuelto 35.00")
        self.assertContains(r, "COBRAR AL ENTREGAR: S/ 65.00")
        # salió y se entregó; aún falta cobrar: sigue abierta
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "salio", "repartidor": "Carlos"})
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "entregado"})
        c.refresh_from_db()
        self.assertEqual((c.estado_envio, c.repartidor, c.abierta), ("ENT", "Carlos", True))
        # el cajero cobra lo que trajo el repartidor: se cierra
        self.client.force_login(self.cajero)
        self.assertTrue(self.client.get(reverse("mesas:cuenta", args=[c.pk])).context["liberar_al_cobrar"])
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps({"pagos": [{"metodo": "EFE", "monto": "100"}]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.estado, Cuenta.Estado.COBRADA)
        from ventas.models import Venta

        v = Venta.objects.get()
        self.assertEqual((v.total, v.vuelto), (D("65"), D("35")))
        self.assertTrue(v.items.filter(descripcion__startswith="Costo de envío").exists())

    def test_pagado_antes_se_cierra_al_entregar_y_recuerda_la_direccion(self):
        c = self._nuevo(paga_con="Yape", costo_envio="0")
        self.assertFalse(c.items.exists())  # envío gratis: no hay línea
        agregar(c, [{"variante": self.v.pk}], self.mozo)
        cobrar(c, self.cajero, [{"metodo": "YAP", "monto": "60"}], liberar=False)
        c.refresh_from_db()
        self.assertTrue(c.abierta)
        self.client.force_login(self.mozo)
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "entregado"})
        c.refresh_from_db()
        self.assertEqual((c.estado, c.estado_envio), (Cuenta.Estado.COBRADA, "ENT"))
        # la próxima vez, por el celular aparecen el nombre y la dirección
        r = self.client.get(reverse("mesas:delivery_buscar"), {"tel": "987111222"})
        self.assertEqual((r.json()["nombre"], r.json()["direccion"]), ("Rosa", "Av. Grau 120"))

    def test_cambiar_envio_y_validaciones(self):
        c = self._nuevo()
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "datos", "nombre": "Rosa", "direccion": "Av. Grau 130", "costo_envio": "7"})
        c.refresh_from_db()
        self.assertEqual((c.direccion, c.costo_envio, c.items.get(es_envio=True).precio), ("Av. Grau 130", D("7.00"), D("7.00")))
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "datos", "direccion": "", "costo_envio": "7"})
        c.refresh_from_db()
        self.assertEqual(c.direccion, "Av. Grau 130")  # sin dirección no se guarda
        for malo in ["abc", "-1", "5000"]:
            self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "datos", "direccion": "X", "costo_envio": malo})
        c.refresh_from_db()
        self.assertEqual(c.costo_envio, D("7.00"))
        n = Cuenta.objects.count()
        self._nuevo(direccion="")
        self.assertEqual(Cuenta.objects.count(), n)  # sin dirección no se abre
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["delivery"])
        self._nuevo()
        self.assertEqual(Cuenta.objects.count(), n)  # apagado: no se puede


class DeliverySinMesasTests(TestCase):
    """Una tienda sin mesas puede hacer delivery: pedido, despacho, cobro y reporte, sin cocina."""

    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["mesas", "cocina"], "delivery_costo": D("5")})
        self.vendedor = User.objects.create_user("vendedor", password="x-clave-123")
        self.vendedor.groups.add(Group.objects.get(name="Vendedor"))
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir(self.cajero, D("50"))
        arroz = Producto.objects.create(nombre="Arroz Costeño 5 kg", precio=D("24"))
        self.arroz = asegurar_variante_unica(arroz)
        mover_stock(self.arroz, 10, MovimientoStock.Tipo.INGRESO)

    def test_flujo_de_tienda(self):
        self.client.force_login(self.vendedor)
        inicio = self.client.get(reverse("core:inicio"))
        self.assertContains(inicio, reverse("mesas:pedidos"))
        self.assertNotContains(inicio, f'href="{reverse("mesas:mapa")}"')
        self.assertEqual(self.client.get(reverse("mesas:mapa")).status_code, 403)
        r = self.client.post(reverse("mesas:delivery_nuevo"), {"telefono": "987111222", "nombre": "Carla", "direccion": "Av. Grau 120"})
        c = Cuenta.objects.get(tipo=Cuenta.Tipo.DELIVERY)
        self.assertRedirects(r, reverse("mesas:agregar", args=[c.pk]))
        self.assertNotContains(self.client.get(reverse("mesas:agregar", args=[c.pk])), "Agregar y enviar")
        r = self.client.post(reverse("mesas:agregar", args=[c.pk]), json.dumps({"items": [{"variante": self.arroz.pk, "cantidad": "2"}], "enviar": True}),
                             content_type="application/json")
        self.assertEqual(r.json()["ok"], True)
        it = c.items.get(es_envio=False)
        self.assertIsNone(it.enviado_en)  # sin cocina: sigue editable con + y −
        r = self.client.get(reverse("mesas:cuenta", args=[c.pk]))
        self.assertNotContains(r, "Enviar a cocina")
        self.assertContains(r, reverse("mesas:pedidos"))
        self.assertContains(self.client.get(reverse("mesas:pedidos")), "Carla")
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "salio", "repartidor": "Luis"})
        it.refresh_from_db()
        self.assertIsNotNone(it.enviado_en)  # lo que salió ya no se cambia
        # el vendedor no cobra; el cajero sí
        datos = {"pagos": [{"metodo": "EFE", "monto": "53"}], "token": "t1"}
        self.assertEqual(self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps(datos), content_type="application/json").status_code, 403)
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("mesas:cobrar", args=[c.pk]), json.dumps(datos), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("volver=/mesas/delivery/", r.json()["url"])
        self.client.post(reverse("mesas:delivery", args=[c.pk]), {"accion": "entregado"})
        c.refresh_from_db()
        self.assertEqual(c.estado, Cuenta.Estado.COBRADA)
        self.arroz.refresh_from_db()
        self.assertEqual(self.arroz.stock, D("8"))
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(jefe)
        r = self.client.get(reverse("reportes:inicio"))
        self.assertContains(r, 'id="delivery"')
        self.assertContains(r, "en productos")

    def test_una_mesa_sigue_pidiendo_permisos_de_mesas(self):
        a = Ajustes.cargar()
        a.modulos_inactivos = ["cocina"]
        a.save()
        mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        cajero_mesas = abrir_cuenta(self.cajero, mesa, 2)
        solo_delivery = User.objects.create_user("repartidor", password="x-clave-123")
        g = Group.objects.create(name="Despacho")
        from core.models import PermisosRol

        PermisosRol.objects.create(grupo=g, permisos=["delivery.atender"])
        solo_delivery.groups.add(g)
        self.client.force_login(solo_delivery)
        self.assertEqual(self.client.get(reverse("mesas:cuenta", args=[cajero_mesas.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("mesas:pedidos")).status_code, 200)

    def test_desde_vender(self):
        """El carrito de Vender pasa a un pedido de delivery, con el precio cambiado si quien lo hace puede cambiar precios."""
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, "Enviar por delivery")
        items = json.dumps([{"variante": self.arroz.pk, "cantidad": "3", "precio": "22.00", "opciones": []}])
        r = self.client.post(reverse("mesas:delivery_nuevo"), {"telefono": "987000111", "nombre": "Luis", "direccion": "Jr. Ica 300",
                                                               "items": items})
        c = Cuenta.objects.get(tipo=Cuenta.Tipo.DELIVERY)
        self.assertRedirects(r, reverse("mesas:cuenta", args=[c.pk]) + "?desde_venta=1")
        it = c.items.get(es_envio=False)
        self.assertEqual((it.cantidad, it.precio), (D("3"), D("24")))  # el cajero no puede cambiar precios
        self.assertEqual(c.items.get(es_envio=True).precio, D("5"))
        r = self.client.get(reverse("mesas:cuenta", args=[c.pk]) + "?desde_venta=1")
        self.assertContains(r, 'sessionStorage.removeItem("pos_carrito_')
        self.assertContains(self.client.get(reverse("core:inicio")), reverse("mesas:pedidos"))
        # si algo falla, vuelve a Vender con el carrito intacto
        malo = json.dumps([{"variante": 999999, "cantidad": "1"}])
        r = self.client.post(reverse("mesas:delivery_nuevo"), {"telefono": "987000222", "direccion": "x", "items": malo})
        self.assertRedirects(r, reverse("ventas:pos"), fetch_redirect_response=False)
        self.assertEqual(Cuenta.objects.filter(tipo=Cuenta.Tipo.DELIVERY).count(), 1)
