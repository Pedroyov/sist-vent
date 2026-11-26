from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from core.models import PermisosRol

from .models import Categoria, MovimientoStock, Producto, Variante
from .servicios import ajustar_a, asegurar_variante_unica, generar_variantes, mover_stock

D = Decimal


def crear_usuario(nombre, rol=None, superusuario=False):
    u = User.objects.create_user(nombre, password="clave-segura-123", is_superuser=superusuario)
    if rol:
        u.groups.add(Group.objects.get(name=rol))
    return u


class StockTests(TestCase):
    def setUp(self):
        self.p = Producto.objects.create(nombre="Polo", precio=D("30"))
        self.v = asegurar_variante_unica(self.p)

    def test_movimientos_y_saldo(self):
        mover_stock(self.v, 10, MovimientoStock.Tipo.INGRESO, costo_unitario=D("12"))
        mover_stock(self.v, -3, MovimientoStock.Tipo.SALIDA)
        self.v.refresh_from_db()
        self.assertEqual(self.v.stock, D("7"))
        self.assertEqual(self.v.costo, D("12"))
        self.assertEqual(MovimientoStock.objects.first().saldo, D("7"))
        mov = ajustar_a(self.v, D("5"))
        self.assertEqual(mov.cantidad, D("-2"))
        self.assertIsNone(ajustar_a(self.v, D("5")))

    def test_generar_variantes(self):
        creadas, existian = generar_variantes(self.p, "S, M, m", "Negro, Blanco")
        self.assertEqual((creadas, existian), (4, 0))  # "m" repetida no cuenta
        self.assertFalse(self.p.variantes.filter(nombre="").exists())
        self.assertEqual(generar_variantes(self.p, "S", "Negro"), (0, 1))

    def test_no_genera_variantes_con_stock_sin_variante(self):
        mover_stock(self.v, 2, MovimientoStock.Tipo.INGRESO)
        with self.assertRaises(ValueError):
            generar_variantes(self.p, "S, M")


class VistasTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario("admin", superusuario=True)
        self.cajero = crear_usuario("cajero", "Cajero")
        self.cat = Categoria.objects.create(nombre="Polos")

    def test_permisos_por_defecto_de_roles(self):
        self.assertIn("productos.ver", PermisosRol.objects.get(grupo__name="Cajero").permisos)
        self.assertIn("productos.ver", PermisosRol.objects.get(grupo__name="Vendedor").permisos)
        self.assertNotIn("productos.editar", PermisosRol.objects.get(grupo__name="Cajero").permisos)

    def test_cajero_ve_pero_no_edita(self):
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("productos:lista")).status_code, 200)
        self.assertEqual(self.client.get(reverse("productos:nuevo")).status_code, 403)
        self.assertEqual(self.client.get(reverse("productos:kardex")).status_code, 403)

    def test_crear_producto_con_stock_y_variantes(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("productos:nuevo"), {
            "tipo": "P", "nombre": "  Polo   básico ", "categoria": self.cat.pk, "unidad": "UND", "precio": "29.90",
            "costo": "15", "maneja_stock": "on", "stock_minimo": "2", "stock_inicial": "6", "codigo": "775001", "activo": "on"})
        p = Producto.objects.get()
        self.assertRedirects(r, reverse("productos:detalle", args=[p.pk]))
        self.assertEqual(p.nombre, "Polo básico")
        v = p.variante_unica()
        self.assertEqual((v.codigo, v.stock), ("775001", D("6")))
        # código repetido
        r = self.client.post(reverse("productos:nuevo"), {"tipo": "P", "nombre": "Otro", "unidad": "UND", "precio": "1",
                                                          "codigo": "775001", "activo": "on"})
        self.assertContains(r, "Ese código ya lo tiene")
        # con stock no se pueden crear variantes; tras el conteo en 0 sí
        self.client.post(reverse("productos:variantes_generar", args=[p.pk]), {"opciones1": "S, M"})
        self.assertFalse(p.tiene_variantes)
        self.client.post(reverse("productos:movimiento", args=[p.pk]), {"variante": v.pk, "operacion": "AJU", "cantidad": "0"})
        self.client.post(reverse("productos:variantes_generar", args=[p.pk]), {"opciones1": "S, M", "opciones2": "Negro"})
        self.assertEqual(list(p.variantes.filter(activa=True).values_list("nombre", flat=True)), ["S / Negro", "M / Negro"])
        for url in ("productos:detalle", "productos:editar", "productos:movimiento"):
            self.assertEqual(self.client.get(reverse(url, args=[p.pk])).status_code, 200)

    def test_servicio_no_maneja_stock(self):
        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"funciones_inactivas": []})
        self.client.force_login(self.admin)
        self.client.post(reverse("productos:nuevo"), {"tipo": "S", "nombre": "Corte", "unidad": "UND", "precio": "25",
                                                     "maneja_stock": "on", "stock_inicial": "5", "duracion_min": "30", "activo": "on"})
        p = Producto.objects.get()
        self.assertFalse(p.maneja_stock)
        self.assertEqual(p.unidad, "SRV")
        self.assertFalse(MovimientoStock.objects.exists())

    def test_ingreso_salida_y_no_borrar_con_historial(self):
        self.client.force_login(self.admin)
        p = Producto.objects.create(nombre="Arroz", precio=D("4.2"), unidad="KG")
        v = asegurar_variante_unica(p)
        url = reverse("productos:movimiento", args=[p.pk])
        self.client.post(url, {"variante": v.pk, "operacion": "ING", "cantidad": "10.5", "costo_unitario": "3.5"})
        self.client.post(url, {"variante": v.pk, "operacion": "SAL", "cantidad": "0.5"})
        v.refresh_from_db()
        self.assertEqual(v.stock, D("10"))
        self.client.post(reverse("productos:eliminar", args=[p.pk]))
        self.assertTrue(Producto.objects.filter(pk=p.pk).exists())
        r = self.client.get(reverse("productos:lista") + "?q=arroz")
        self.assertContains(r, "Arroz")
        self.assertEqual(self.client.get(reverse("productos:kardex") + "?excel=1").status_code, 200)

    def test_lista_filtros_y_exportar(self):
        self.client.force_login(self.admin)
        p = Producto.objects.create(nombre="Leche", precio=D("4"), stock_minimo=D("5"))
        mover_stock(asegurar_variante_unica(p), 3, MovimientoStock.Tipo.INGRESO)
        r = self.client.get(reverse("productos:lista") + "?estado=reponer")
        self.assertContains(r, "Leche")
        r = self.client.get(reverse("productos:exportar"))
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws["A2"].value, "Leche")
        self.assertContains(self.client.get(reverse("core:inicio")), "por reponer")

    def test_categorias(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("productos:categorias"), {"nombre": "Bebidas", "orden": "10", "activa": "on"})
        self.assertTrue(Categoria.objects.filter(nombre="Bebidas").exists())
        self.client.post(reverse("productos:categorias_sugeridas"), {"nombre": ["Abarrotes", "Inventada"]})
        self.assertTrue(Categoria.objects.filter(nombre="Abarrotes").exists())
        self.assertFalse(Categoria.objects.filter(nombre="Inventada").exists())

    def _excel(self, filas):
        wb = Workbook()
        ws = wb.active
        ws.append(["Producto *", "Variante", "Código", "Categoría", "Tipo", "Unidad", "Precio *", "Costo", "Stock", "Stock mínimo"])
        for f in filas:
            ws.append(f)
        buf = BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("p.xlsx", buf.getvalue())

    def test_importar(self):
        self.client.force_login(self.admin)
        url = reverse("productos:importar")
        archivo = self._excel([
            ["Polo", "M", "", "Polos", "", "", 30, 15, 4, 1],
            ["Polo", "L", "", "Polos", "", "", 32, 15, 2, 1],
            ["Arroz", "", 7750001, "Abarrotes", "Producto", "kilo", "4.20", "", "50.5", ""],
            ["Corte", "", "", "Cortes", "Servicio", "", 25, "", "", ""],
        ])
        r = self.client.post(url, {"archivo": archivo})
        self.assertContains(r, "Confirmar importación")
        self.client.post(url, {"confirmar": "1"})
        polo = Producto.objects.get(nombre="Polo")
        self.assertEqual(polo.variantes.get(nombre="L").precio_venta, D("32"))
        self.assertEqual(polo.stock_total, D("6"))
        arroz = Variante.objects.get(codigo="7750001")
        self.assertEqual((arroz.stock, arroz.producto.unidad), (D("50.5"), "KG"))
        self.assertFalse(Producto.objects.get(nombre="Corte").maneja_stock)
        # segunda vez: actualiza precio y ajusta stock
        r = self.client.post(url, {"archivo": self._excel([["Arroz", "", "7750001", "", "", "", "4.50", "", "40", ""]])})
        self.assertContains(r, "Actualizar")
        self.client.post(url, {"confirmar": "1"})
        arroz.refresh_from_db()
        self.assertEqual((arroz.stock, arroz.producto.precio), (D("40"), D("4.50")))
        # errores: no guarda nada
        r = self.client.post(url, {"archivo": self._excel([["", "", "", "", "", "", "x", "", "", ""]])})
        self.assertContains(r, "con problemas")
        self.assertEqual(self.client.get(reverse("productos:plantilla")).status_code, 200)


class OpcionesYAgotadosTests(TestCase):
    def setUp(self):
        from caja.servicios import abrir
        from core.models import Ajustes

        from .models import GrupoOpciones, Opcion

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "nivel_pedido": 2})
        self.jefe = crear_usuario("jefe", "Administración")
        self.mozo = crear_usuario("mozo", "Vendedor")
        self.chef = crear_usuario("chef", "Cocina")
        abrir(self.jefe, D("0"))
        self.termino = GrupoOpciones.objects.create(nombre="Término", minimo=1, maximo=1)
        self.medio = Opcion.objects.create(grupo=self.termino, nombre="Medio")
        self.cocido = Opcion.objects.create(grupo=self.termino, nombre="Bien cocido")
        self.extras = GrupoOpciones.objects.create(nombre="Adicionales", minimo=0, maximo=2)
        self.huevo = Opcion.objects.create(grupo=self.extras, nombre="Huevo", precio=D("2"))
        self.queso = Opcion.objects.create(grupo=self.extras, nombre="Queso", precio=D("3"))
        self.papas = Opcion.objects.create(grupo=self.extras, nombre="Papas", precio=D("5"))
        self.lomo = Producto.objects.create(nombre="Lomo", precio=D("20"), maneja_stock=False)
        self.lomo.grupos.set([self.termino, self.extras])
        self.v = asegurar_variante_unica(self.lomo)
        self.otro = Producto.objects.create(nombre="Otro", precio=D("1"), maneja_stock=False)

    def test_reglas(self):
        from .servicios import OpcionInvalida, marcar_agotado, resolver_opciones

        with self.assertRaisesMessage(OpcionInvalida, "elige término"):
            resolver_opciones(self.lomo, [])
        with self.assertRaisesMessage(OpcionInvalida, "hasta 1"):
            resolver_opciones(self.lomo, [self.medio.pk, self.cocido.pk])
        with self.assertRaisesMessage(OpcionInvalida, "hasta 2"):
            resolver_opciones(self.lomo, [self.medio.pk, self.huevo.pk, self.queso.pk, self.papas.pk])
        with self.assertRaisesMessage(OpcionInvalida, "ya no está disponible"):
            resolver_opciones(self.otro, [self.medio.pk])
        foto, extra, texto = resolver_opciones(self.lomo, [self.queso.pk, self.medio.pk, self.huevo.pk])
        self.assertEqual(([o["n"] for o in foto], extra), (["Medio", "Huevo", "Queso"], D("5")))
        self.assertEqual(texto, "Medio, Huevo +2.00, Queso +3.00")
        marcar_agotado(self.huevo)
        with self.assertRaisesMessage(OpcionInvalida, "agotado"):
            resolver_opciones(self.lomo, [self.medio.pk, self.huevo.pk])
        type(self.huevo).objects.filter(pk=self.huevo.pk).update(agotada_en=timezone.now() - timedelta(days=1))
        self.huevo.refresh_from_db()
        self.assertFalse(self.huevo.agotada)  # al día siguiente vuelve solo

    def test_venta_y_mesa_con_opciones(self):
        from mesas.models import Mesa, Zona
        from mesas.servicios import MesaError, abrir_cuenta, agregar, cobrar
        from ventas.servicios import VentaInvalida, registrar_venta

        from .servicios import marcar_agotado

        venta = registrar_venta(self.jefe, [{"variante": self.v.pk, "cantidad": "2", "opciones": [self.medio.pk, self.huevo.pk]}],
                                [{"metodo": "EFE", "monto": "44"}])
        item = venta.items.get()
        self.assertEqual((venta.total, item.descripcion, item.precio_lista), (D("44"), "Lomo (Medio, Huevo)", D("22")))
        with self.assertRaisesMessage(VentaInvalida, "elige término"):
            registrar_venta(self.jefe, [{"variante": self.v.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "20"}])
        c = abrir_cuenta(self.mozo, Mesa.objects.create(zona=Zona.objects.create(nombre="S"), nombre="1"))
        agregar(c, [{"variante": self.v.pk, "cantidad": 1, "opciones": [self.medio.pk, self.queso.pk]}], self.mozo)
        agregar(c, [{"variante": self.v.pk, "cantidad": 1, "opciones": [self.queso.pk, self.medio.pk]}], self.mozo)
        agregar(c, [{"variante": self.v.pk, "cantidad": 1, "opciones": [self.cocido.pk]}], self.mozo)
        self.assertEqual(sorted((i.cantidad, i.precio, i.texto_opciones) for i in c.items.all()),
                         [(D("1"), D("20"), "Bien cocido"), (D("2"), D("23"), "Medio, Queso")])
        marcar_agotado(self.lomo)
        with self.assertRaisesMessage(MesaError, "agotado"):
            agregar(c, [{"variante": self.v.pk, "cantidad": 1, "opciones": [self.medio.pk]}], self.mozo)
        with self.assertRaisesMessage(VentaInvalida, "agotado"):
            registrar_venta(self.jefe, [{"variante": self.v.pk, "cantidad": "1", "opciones": [self.medio.pk]}], [])
        v2 = cobrar(c, self.jefe, [{"metodo": "EFE", "monto": "66"}])  # lo ya pedido se cobra igual
        self.assertEqual(v2.total, D("66"))
        self.assertIn("Lomo (Medio, Queso)", [i.descripcion for i in v2.items.all()])

    def test_pantallas(self):
        from .models import GrupoOpciones

        self.client.force_login(self.jefe)
        r = self.client.post(reverse("productos:grupo_nuevo"), {
            "nombre": "Cremas", "minimo": "0", "maximo": "0", "orden": "10", "activo": "on",
            "opciones_texto": "Mayonesa\nAjí\nHuancaína | 1.50\n", "productos": [self.lomo.pk]})
        self.assertRedirects(r, reverse("productos:opciones"))
        g = GrupoOpciones.objects.get(nombre="Cremas")
        self.assertEqual([(o.nombre, o.precio) for o in g.opciones.all()], [("Mayonesa", D("0")), ("Ají", D("0")), ("Huancaína", D("1.50"))])
        self.assertIn(g, self.lomo.grupos.all())
        aji = g.opciones.get(nombre="Ají")
        self.client.post(reverse("productos:grupo_editar", args=[g.pk]), {
            "nombre": "Cremas", "minimo": "0", "maximo": "0", "orden": "10", "activo": "on", "opciones_texto": "Ají\nTártara", "productos": []})
        aji.refresh_from_db()
        self.assertEqual((aji.orden, aji.activa), (0, True))
        self.assertFalse(g.opciones.get(nombre="Mayonesa").activa)
        self.assertNotIn(g, self.lomo.grupos.all())
        r = self.client.post(reverse("productos:grupo_nuevo"), {"nombre": "X", "minimo": "3", "maximo": "1", "orden": "1", "opciones_texto": "a\nb"})
        self.assertContains(r, "no puede ser mayor")
        self.client.force_login(self.chef)
        self.client.post(reverse("productos:agotados"), {"producto": self.lomo.pk, "agotado": "1"})
        self.lomo.refresh_from_db()
        self.assertTrue(self.lomo.agotado)
        self.assertContains(self.client.get(reverse("productos:agotados")), "AGOTADO")
        self.client.force_login(self.mozo)
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, '"ag": true')


class MenuDelDiaTests(TestCase):
    """El menú: un producto de precio fijo con entrada y segundo que cambian cada día."""

    def setUp(self):
        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": [], "rubro": "RES", "nombre": "El Buen Sabor", "nivel_pedido": 2})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.vendedor = User.objects.create_user("vendedor", password="x-clave-123")
        self.vendedor.groups.add(Group.objects.get(name="Vendedor"))
        cat = Categoria.objects.create(nombre="Menú del día")
        self.menu = Producto.objects.create(nombre="Menú ejecutivo", precio=Decimal("15"), categoria=cat, maneja_stock=False)
        asegurar_variante_unica(self.menu)
        self.url = reverse("productos:menu")

    def test_armar_el_menu_y_pedirlo(self):
        from .models import GrupoOpciones, Opcion
        from .servicios import OpcionInvalida, resolver_opciones

        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(self.url).status_code, 403)  # el mozo no arma el menú
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("core:inicio"))
        self.assertContains(r, self.url)  # aparece en el menú lateral
        self.client.post(self.url, {"accion": "crear"})
        entrada, segundo = GrupoOpciones.objects.filter(diario=True).order_by("orden")
        self.assertEqual(set(self.menu.grupos.all()), {entrada, segundo})
        for g, nombre, precio in [(entrada, "Sopa de casa", ""), (entrada, "Causa", ""), (segundo, "Arroz con pollo", ""),
                                  (segundo, "Pescado frito", "3")]:
            self.client.post(self.url, {"accion": "agregar", "grupo": g.pk, "nombre": nombre, "precio": precio})
        sopa = Opcion.objects.get(nombre="Sopa de casa")
        pescado = Opcion.objects.get(nombre="Pescado frito")
        self.assertEqual(pescado.precio, Decimal("3.00"))
        _, extra, texto = resolver_opciones(self.menu, [sopa.pk, pescado.pk])
        self.assertEqual((extra, texto), (Decimal("3.00"), "Sopa de casa, Pescado frito +3.00"))
        with self.assertRaises(OpcionInvalida):  # hay que elegir segundo
            resolver_opciones(self.menu, [sopa.pk])
        # texto para WhatsApp
        r = self.client.get(self.url)
        self.assertContains(r, "*Menú ejecutivo · S/ 15.00*")
        self.assertContains(r, "_Entrada:_ Sopa de casa")
        self.assertContains(r, "Pescado frito (+S/ 3.00)")
        # al día siguiente: se vacía, el pescado queda guardado y se vuelve a poner con un toque
        self.client.post(self.url, {"accion": "limpiar"})
        self.assertFalse(Opcion.objects.filter(grupo__diario=True, activa=True).exists())
        self.client.post(self.url, {"accion": "poner", "opcion": pescado.pk})
        self.client.post(self.url, {"accion": "agregar", "grupo": segundo.pk, "nombre": "  arroz CON pollo "})  # ya existía: no se duplica
        self.assertEqual(Opcion.objects.filter(grupo=segundo).count(), 2)
        self.assertEqual(Opcion.objects.filter(grupo=segundo, activa=True).count(), 2)
        # hoy no hay entradas: el menú se puede pedir igual (solo con segundo)
        foto, _, _ = resolver_opciones(self.menu, [pescado.pk])
        self.assertEqual(len(foto), 1)
        # se acabó el pescado
        self.client.post(self.url, {"accion": "agotar", "opcion": pescado.pk})
        pescado.refresh_from_db()
        self.assertTrue(pescado.agotada)
        with self.assertRaises(OpcionInvalida):
            resolver_opciones(self.menu, [pescado.pk])

    def test_datos_no_validos(self):
        self.client.force_login(self.cajero)
        self.client.post(self.url, {"accion": "crear"})
        from .models import GrupoOpciones, Opcion

        g = GrupoOpciones.objects.filter(diario=True).first()
        for precio in ["abc", "-1", "nan", "99999"]:
            self.client.post(self.url, {"accion": "agregar", "grupo": g.pk, "nombre": "X", "precio": precio})
        self.client.post(self.url, {"accion": "agregar", "grupo": g.pk, "nombre": "   "})
        self.assertFalse(Opcion.objects.exists())
        otro = GrupoOpciones.objects.create(nombre="Término", minimo=1, maximo=1)  # no es del menú: no se toca desde aquí
        self.assertEqual(self.client.post(self.url, {"accion": "agregar", "grupo": otro.pk, "nombre": "Y"}).status_code, 404)


class OpcionesIncluidasTests(TestCase):
    """Lo que viene con el plato (alitas con papas) ya va elegido; si el cliente quiere otra cosa, se cambia."""

    def setUp(self):
        from core.models import Ajustes

        from .models import GrupoOpciones, Opcion

        Ajustes.objects.update_or_create(pk=1, defaults={"nivel_pedido": 2})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.alitas = Producto.objects.create(nombre="Alitas", precio=Decimal("18"), maneja_stock=False)
        asegurar_variante_unica(self.alitas)

    def test_linea(self):
        from .servicios import leer_linea_opcion

        self.assertEqual(leer_linea_opcion("Papas fritas *"), ("Papas fritas", Decimal("0.00"), True))
        self.assertEqual(leer_linea_opcion("* Arroz"), ("Arroz", Decimal("0.00"), True))
        self.assertEqual(leer_linea_opcion("Huevo frito | 2,50"), ("Huevo frito", Decimal("2.50"), False))
        self.assertEqual(leer_linea_opcion("Queso | 3 *"), ("Queso", Decimal("3.00"), True))
        with self.assertRaises(ValueError):
            leer_linea_opcion("X | 1.2.3")

    def test_formulario_y_pedido(self):
        from .models import GrupoOpciones, Opcion
        from .servicios import resolver_opciones

        self.client.force_login(self.jefe)
        datos = {"nombre": "Acompañamiento", "minimo": 1, "maximo": 1, "orden": 1, "activo": "on",
                 "opciones_texto": "Papas fritas *\nArroz *\nEnsalada", "productos": [self.alitas.pk]}
        r = self.client.post(reverse("productos:grupo_nuevo"), datos)
        self.assertContains(r, "solo una puede venir incluida")
        datos["opciones_texto"] = "Papas fritas *\nArroz\nEnsalada"
        self.assertEqual(self.client.post(reverse("productos:grupo_nuevo"), datos).status_code, 302)
        g = GrupoOpciones.objects.get()
        papas = Opcion.objects.get(nombre="Papas fritas")
        self.assertTrue(papas.por_defecto)
        r = self.client.get(reverse("productos:grupo_editar", args=[g.pk]))
        self.assertContains(r, "Papas fritas *")
        # el mozo no eligió nada: van las papas; si eligió ensalada, va ensalada
        _, _, texto = resolver_opciones(self.alitas, [])
        self.assertEqual(texto, "Papas fritas")
        _, _, texto = resolver_opciones(self.alitas, [Opcion.objects.get(nombre="Ensalada").pk])
        self.assertEqual(texto, "Ensalada")
        # en el catálogo del punto de venta y de las mesas sale marcada
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, '"d": true')


class QueLlevaTests(TestCase):
    """Qué lleva el plato: se puede quitar ("SIN ENSALADA") o cambiar (papas por arroz)."""

    def setUp(self):
        from core.models import Ajustes

        from .models import GrupoOpciones, Opcion

        Ajustes.objects.update_or_create(pk=1, defaults={"nivel_pedido": 3})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.pollo = Producto.objects.create(nombre="Pollo a la brasa", precio=Decimal("18"), maneja_stock=False)
        asegurar_variante_unica(self.pollo)
        self.acomp = GrupoOpciones.objects.create(nombre="Acompañamiento", minimo=1, maximo=1)
        self.papas = Opcion.objects.create(grupo=self.acomp, nombre="Papas fritas", por_defecto=True)
        self.arroz = Opcion.objects.create(grupo=self.acomp, nombre="Arroz")
        self.url = reverse("productos:componentes", args=[self.pollo.pk])

    def test_armar_y_pedir(self):
        from mesas.models import Mesa, Zona
        from mesas.servicios import abrir_cuenta, agregar

        from .servicios import OpcionInvalida, resolver_opciones

        self.client.force_login(self.jefe)
        self.client.post(self.url, {"accion": "agregar", "nombre": "Pollo"})  # sin marcar "se puede quitar": siempre va
        self.client.post(self.url, {"accion": "agregar", "nombre": "Papas fritas", "cambiar_con": self.acomp.pk})
        self.client.post(self.url, {"accion": "agregar", "nombre": "Ensalada, Cremas", "quitable": "1"})  # varios a la vez
        self.client.post(self.url, {"accion": "agregar", "nombre": "ensalada", "quitable": "1"})  # repetido: no se duplica
        pollo_c, papas_c, ensalada, cremas = self.pollo.componentes.all()
        self.assertEqual([c.nombre for c in (pollo_c, papas_c, ensalada, cremas)], ["Pollo", "Papas fritas", "Ensalada", "Cremas"])
        self.assertFalse(pollo_c.quitable)
        self.assertIn(self.acomp, self.pollo.grupos.all())  # para poder cambiar, el grupo queda en el plato
        self.assertContains(self.client.get(reverse("productos:detalle", args=[self.pollo.pk])), "Qué lleva")
        # se ordena y se cambia
        self.client.post(self.url, {"accion": "subir", "componente": cremas.pk})
        self.assertEqual([c.nombre for c in self.pollo.componentes.all()][2], "Cremas")
        self.client.post(self.url, {"accion": "quitable", "componente": cremas.pk})
        cremas.refresh_from_db()
        self.assertFalse(cremas.quitable)
        # al pedir: sin ensalada y con arroz en vez de papas
        foto, extra, texto = resolver_opciones(self.pollo, [self.arroz.pk, f"s{ensalada.pk}"])
        self.assertEqual((texto, extra), ("Arroz, SIN ENSALADA", Decimal("0")))
        with self.assertRaises(OpcionInvalida):  # el pollo no se puede quitar
            resolver_opciones(self.pollo, [f"s{pollo_c.pk}"])
        with self.assertRaises(OpcionInvalida):
            resolver_opciones(self.pollo, ["sx"])
        # en la mesa: dos pedidos iguales se juntan, uno distinto va aparte; la comanda dice SIN
        mesa = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        c = abrir_cuenta(self.jefe, mesa)
        v = self.pollo.variantes.get()
        agregar(c, [{"variante": v.pk, "opciones": [f"s{ensalada.pk}"]}, {"variante": v.pk, "opciones": [f"s{ensalada.pk}"]},
                    {"variante": v.pk}], self.jefe)
        self.assertEqual(sorted((i.cantidad, i.texto_opciones) for i in c.items.all()),
                         [(Decimal("1"), "Papas fritas"), (Decimal("2"), "Papas fritas, SIN ENSALADA")])
        # el catálogo lleva lo que lleva
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, '"n": "Ensalada", "q": true')
        # se borra
        self.client.post(self.url, {"accion": "borrar", "componente": ensalada.pk})
        self.assertEqual(self.pollo.componentes.count(), 3)

    def test_solo_quien_edita_productos(self):
        cajero = User.objects.create_user("cajero", password="x-clave-123")
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        self.assertEqual(self.client.post(self.url, {"accion": "agregar", "nombre": "X"}).status_code, 403)
        self.assertNotContains(self.client.get(reverse("productos:detalle", args=[self.pollo.pk])), "Escribe lo que lleva")


class NivelDePedidoTests(TestCase):
    """Simple / con opciones / detallado: lo que no se usa no aparece ni se pide."""

    def setUp(self):
        from core.models import Ajustes

        from .models import Componente, GrupoOpciones, Opcion

        self.aj, _ = Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "funciones_inactivas": [], "rubro": "RES"})
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.lomo = Producto.objects.create(nombre="Lomo", precio=Decimal("28"), maneja_stock=False)
        asegurar_variante_unica(self.lomo)
        g = GrupoOpciones.objects.create(nombre="Término", minimo=1, maximo=1)
        self.medio = Opcion.objects.create(grupo=g, nombre="Medio")
        self.lomo.grupos.add(g)
        self.cebolla = Componente.objects.create(producto=self.lomo, nombre="Cebolla")
        self.client.force_login(self.jefe)

    def _nivel(self, n):
        self.aj.nivel_pedido = n
        self.aj.save()

    def test_simple(self):
        from .servicios import resolver_opciones

        self._nivel(1)
        self.assertEqual(resolver_opciones(self.lomo, []), ([], Decimal("0"), ""))  # el término ya no se exige
        self.assertNotContains(self.client.get(reverse("ventas:pos")), '"n": "Medio"')
        r = self.client.get(reverse("productos:detalle", args=[self.lomo.pk]))
        self.assertNotContains(r, "Qué lleva")
        self.assertNotContains(r, reverse("productos:opciones"))
        self.assertContains(self.client.get(reverse("productos:menu")), "Con opciones")
        # editar el producto en modo simple no le borra sus opciones (por si vuelven a activarlas)
        r = self.client.get(reverse("productos:editar", args=[self.lomo.pk]))
        self.assertContains(r, 'class="card mb-4 d-none"')

    def test_con_opciones_sin_lleva(self):
        from .servicios import OpcionInvalida, resolver_opciones

        self._nivel(2)
        with self.assertRaises(OpcionInvalida):
            resolver_opciones(self.lomo, [])  # el término se exige... salvo que tenga algo incluido
        _, _, texto = resolver_opciones(self.lomo, [self.medio.pk, f"s{self.cebolla.pk}"])
        self.assertEqual(texto, "Medio")  # "qué lleva" está apagado: no se quita nada
        self.assertNotContains(self.client.get(reverse("productos:detalle", args=[self.lomo.pk])), "Qué lleva")
        self.assertContains(self.client.get(reverse("ventas:pos")), '"k": []')

    def test_detallado_y_formulario(self):
        from .servicios import resolver_opciones

        self._nivel(3)
        _, _, texto = resolver_opciones(self.lomo, [self.medio.pk, f"s{self.cebolla.pk}"])
        self.assertEqual(texto, "Medio, SIN CEBOLLA")
        self.assertContains(self.client.get(reverse("productos:detalle", args=[self.lomo.pk])), "Qué lleva")
        r = self.client.get(reverse("core:datos_negocio"))
        self.assertContains(r, "Cómo se toman los pedidos")
