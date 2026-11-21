"""Bitácora: lo crítico queda anotado con quién, cuándo y desde dónde, y nadie lo puede cambiar sin que se note."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.db import connection, transaction
from django.test import TestCase
from django.urls import reverse

from productos.models import MovimientoStock, Producto
from productos.servicios import asegurar_variante_unica, mover_stock

from .bitacora import anotar, verificar
from .models import Bitacora

D = Decimal


class Base(TestCase):
    def setUp(self):
        from core.models import Ajustes

        Ajustes.objects.update_or_create(pk=1, defaults={"vender_sin_caja": True})
        self.admin = User.objects.create_user("admin", password="x-clave-123", is_superuser=True)
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.p = Producto.objects.create(nombre="Arroz", precio=D("4.20"), costo=D("3"))
        self.v = asegurar_variante_unica(self.p)
        mover_stock(self.v, 10, MovimientoStock.Tipo.INGRESO)

    def acciones(self):
        return list(Bitacora.objects.order_by("n").values_list("accion", flat=True))


class CadenaTests(Base):
    def test_encadena_y_detecta_cambios(self):
        for i in range(3):
            anotar("config.negocio", f"cambio {i}", usuario=self.admin, despues={"monto": D("1.50")})
        filas = list(Bitacora.objects.order_by("n"))
        self.assertEqual([b.n for b in filas], [1, 2, 3])
        self.assertEqual(filas[1].huella_anterior, filas[0].huella)
        self.assertEqual(filas[0].usuario_nombre, "admin")
        self.assertEqual(filas[0].despues, {"monto": "1.50"})
        self.assertTrue(verificar()["ok"])
        # el modelo no deja editar ni borrar
        with self.assertRaises(Exception):
            filas[0].save()
        with self.assertRaises(Exception):
            filas[0].delete()
        if connection.vendor == "postgresql":
            # en producción la base misma lo rechaza
            with self.assertRaises(Exception), transaction.atomic():
                Bitacora.objects.filter(n=2).update(descripcion="otra cosa")
            with self.assertRaises(Exception), transaction.atomic():
                Bitacora.objects.filter(n=2).delete()
            return
        # quien entra a la base por fuera queda en evidencia
        Bitacora.objects.filter(n=2).update(descripcion="otra cosa")
        r = verificar()
        self.assertEqual((r["ok"], r["rota_en"]), (False, 2))
        self.assertIn("cambiado", r["motivo"])
        Bitacora.objects.filter(n=2).delete()
        r = verificar()
        self.assertEqual((r["ok"], r["rota_en"]), (False, 2))
        self.assertIn("borradas", r["motivo"])


class AccionesTests(Base):
    def test_venta_descuento_precio_y_anulacion(self):
        from ventas.servicios import anular_venta, registrar_venta

        v = registrar_venta(self.admin, [{"variante": self.v.pk, "cantidad": "2", "precio": "4.00"}], [{"metodo": "TAR", "monto": "7"}],
                            descuento="1", puede_cambiar_precio=True)
        normal = registrar_venta(self.cajero, [{"variante": self.v.pk, "cantidad": "1"}], [{"metodo": "TAR", "monto": "4.20"}])
        self.assertEqual(self.acciones(), ["venta.descuento", "venta.precio"])  # una venta normal no se anota
        anular_venta(normal, self.admin, "cliente devolvió")
        b = Bitacora.objects.first()
        self.assertEqual((b.accion, b.objeto_tipo, b.objeto_id), ("venta.anulada", "venta", str(normal.pk)))
        self.assertIn("cliente devolvió", b.descripcion)
        self.assertTrue(verificar()["ok"])
        self.assertTrue(v)

    def test_stock_caja_y_cliente(self):
        from caja.servicios import abrir, cerrar
        from clientes.models import Cliente

        mover_stock(self.v, -2, MovimientoStock.Tipo.SALIDA, self.admin, nota="merma")
        mover_stock(self.v, 3, MovimientoStock.Tipo.INGRESO, self.admin)  # ingresos normales no
        b = Bitacora.objects.first()
        self.assertEqual((b.accion, b.despues["valor_costo"]), ("stock.salida", "6.00"))
        s = abrir(self.cajero, D("50"))
        cerrar(s, D("45"), self.admin)
        self.assertEqual(self.acciones()[-2:], ["caja.diferencia", "caja.cierre_ajeno"])
        c = Cliente.objects.create(nombre="Rosa", limite_credito=D("100"))
        self.client.force_login(self.admin)
        r = self.client.post(reverse("clientes:editar", args=[c.pk]), {"nombre": "Rosa", "tipo_documento": "SD", "numero_documento": "",
                                                                       "limite_credito": "500", "activo": "on"})
        self.assertIn(r.status_code, (200, 302))
        b = Bitacora.objects.filter(accion="cliente.limite").first()
        self.assertIsNotNone(b, r.context["form"].errors if r.status_code == 200 else "")
        self.assertEqual(b.despues, {"limite": "500"})

    def test_ingreso_permisos_y_modulos(self):
        self.client.post(reverse("login"), {"username": "admin", "password": "x-clave-123"})
        b = Bitacora.objects.first()
        self.assertEqual((b.accion, b.ip), ("ingreso", "127.0.0.1"))
        self.client.logout()
        self.client.post(reverse("login"), {"username": "cajero", "password": "x-clave-123"})
        self.assertEqual(Bitacora.objects.filter(accion="ingreso").count(), 1)  # solo se anota a Administración
        self.client.force_login(self.admin)
        g = Group.objects.get(name="Cajero")
        datos = {"accion": "permisos", f"p_{g.pk}": [p.codename for p in g.permissions.all()] + ["ventas.descuento"]}
        self.client.post(reverse("core:roles"), datos)
        from core.models import Ajustes
        from core.permisos import MODULOS

        activos = [m[0] for m in MODULOS if m[0] not in (Ajustes.cargar().modulos_inactivos or [])]
        self.client.post(reverse("core:modulos"), {"modulo": activos[:-1]})
        self.assertIn("config.modulos", self.acciones())


class PantallaTests(Base):
    def test_solo_administracion_y_excel(self):
        anotar("config.negocio", "Nombre del negocio cambiado", usuario=self.admin)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("core:bitacora")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("core:bitacora"))
        self.assertContains(r, "Nombre del negocio cambiado")
        self.assertContains(r, "Cadena verificada")
        r = self.client.get(reverse("core:bitacora"), {"excel": "1"})
        self.assertEqual(r["Content-Type"][:30], "application/vnd.openxmlformats")
        r = self.client.get(reverse("core:bitacora"), {"q": "nada-que-ver"})
        self.assertNotContains(r, "Nombre del negocio cambiado")
        # en la ficha del producto
        anotar("producto.precio", "Precio de Arroz: 4.20 → 5.00", objeto=self.p, usuario=self.admin)
        self.assertContains(self.client.get(reverse("productos:detalle", args=[self.p.pk])), "Precio de Arroz")
        self.client.force_login(self.cajero)
        self.assertNotContains(self.client.get(reverse("productos:detalle", args=[self.p.pk])), "Precio de Arroz")
