import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir
from core.models import Ajustes
from productos.models import Producto
from productos.servicios import asegurar_variante_unica
from ventas.servicios import registrar_venta

from .forms import PersonaForm
from .models import Persona
from .reportes import reporte

D = Decimal


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina", "citas"], "funciones_inactivas": ["atendio", "comisiones"], "propina_activa": True})
        self.cajero = User.objects.create_user("cajero", first_name="Luis", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.polo = asegurar_variante_unica(Producto.objects.create(nombre="Polo", precio=D("50"), maneja_stock=False))
        self.ana = Persona.objects.create(nombre="Ana", comision=D("10"), atiende_citas=False)
        abrir(self.cajero, D("0"))
        self.hoy = timezone.localdate()

    def funciones(self, *encendidas):
        a = Ajustes.cargar()
        a.funciones_inactivas = [f for f in ("atendio", "comisiones") if f not in encendidas]
        a.save()


class PersonalTests(Base):
    def test_ficha_muestra_solo_lo_que_usa_el_negocio(self):
        f = PersonaForm(modulos={"mostrador"}, comisiones=False)
        self.assertNotIn("servicios", f.fields)
        self.assertNotIn("reparte", f.fields)
        self.assertNotIn("comision", f.fields)
        f = PersonaForm(modulos={"citas", "delivery"}, comisiones=True)
        self.assertTrue({"servicios", "atiende_citas", "reparte", "comision"} <= set(f.fields))
        self.client.force_login(self.jefe)
        resp = self.client.post(reverse("personal:nuevo"), {"nombre": "Beto", "color": "#0d6efd", "orden": 0, "activo": "on"})
        beto = Persona.objects.get(nombre="Beto")
        self.assertRedirects(resp, reverse("personal:persona", args=[beto.pk]))
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("personal:lista")).status_code, 403)  # solo Administración por defecto

    def test_vender_con_quien_atendio_y_comision(self):
        self.client.force_login(self.cajero)
        datos = {"items": [{"variante": self.polo.pk, "cantidad": "2"}], "pagos": [{"metodo": "EFE", "monto": "100"}], "atendio": self.ana.pk}
        # función apagada: no se pregunta ni se guarda
        self.assertNotContains(self.client.get(reverse("ventas:pos")), 'id="atendio"')
        r = self.client.post(reverse("ventas:registrar"), json.dumps({**datos, "token": "a"}), content_type="application/json").json()
        self.assertTrue(r["ok"])
        self.funciones("atendio", "comisiones")
        self.assertContains(self.client.get(reverse("ventas:pos")), 'id="atendio"')
        self.client.post(reverse("ventas:registrar"), json.dumps({**datos, "token": "b"}), content_type="application/json")
        rp = reporte(self.hoy, self.hoy, {"mostrador"}, comisiones=True, atendio=True)
        ana = next(f for f in rp["filas"] if f["persona"] == self.ana)
        self.assertEqual((ana["atendio_n"], ana["atendio"], ana["comision"]), (1, D("100"), D("10.00")))
        luis = next(f for f in rp["filas"] if f["nombre"] == "Luis")  # cajero sin ficha de personal: sale con su usuario
        self.assertEqual((luis["cobro_n"], luis["cobro"], luis["promedio"]), (2, D("200"), D("100.00")))
        self.assertTrue(rp["ver"]["atendio"])
        self.assertFalse(rp["ver"]["servicios"])

    def test_mozo_y_repartidor_en_el_mismo_reporte(self):
        from mesas.models import Cuenta, Mesa, Zona
        from mesas.servicios import abrir_cuenta, agregar, cobrar

        mozo = User.objects.create_user("mozo", password="x-clave-123")
        mozo.groups.add(Group.objects.get(name="Mozo"))
        jorge = Persona.objects.create(nombre="Jorge", usuario=mozo, atiende_citas=False)
        Persona.objects.create(nombre="Carlos (moto)", reparte=True, atiende_citas=False)
        m = Mesa.objects.create(zona=Zona.objects.create(nombre="Salón"), nombre="1")
        c = abrir_cuenta(mozo, m, 2)
        agregar(c, [{"variante": self.polo.pk, "cantidad": 1}], mozo)
        cobrar(c, self.cajero, [{"metodo": "EFE", "monto": "55"}], propina="5")
        d = Cuenta.objects.create(mozo=self.cajero, tipo=Cuenta.Tipo.DELIVERY, nombre="Rosa", direccion="Av. 1", repartidor="carlos (moto)",
                                  estado=Cuenta.Estado.COBRADA)
        rp = reporte(self.hoy, self.hoy, {"mesas", "delivery"})
        fila = next(f for f in rp["filas"] if f["persona"] == jorge)
        self.assertEqual((fila["atendio_n"], fila["propinas"]), (1, D("5")))
        rep = next(f for f in rp["filas"] if f["nombre"] == "Carlos (moto)")
        self.assertEqual(rep["entregas"], 1)  # el nombre escrito se reconoce como la persona
        self.assertTrue(rp["ver"]["propinas"] and rp["ver"]["entregas"])
        # el delivery ofrece a los repartidores del personal
        self.client.force_login(self.cajero)
        d.estado = Cuenta.Estado.ABIERTA
        d.save()
        self.assertEqual(self.client.get(reverse("mesas:cuenta", args=[d.pk])).context["repartidores"][0], "Carlos (moto)")

    def test_reportes_muestra_la_seccion_personal(self):
        registrar_venta(self.cajero, [{"variante": self.polo.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "50"}])
        self.client.force_login(self.jefe)
        resp = self.client.get(reverse("reportes:inicio"))
        self.assertContains(resp, "Cobró en caja")
        self.assertNotContains(resp, "Comisiones a pagar")
        self.assertEqual(self.client.get(reverse("reportes:inicio"), {"excel": 1}).status_code, 200)


class CobrosTests(Base):
    def test_cobro_en_caja_suma_ventas_cuotas_y_deudas(self):
        from clientes.models import Cliente
        from clientes.servicios import registrar_abono
        from cobranzas.models import Plan
        from cobranzas.servicios import cobrar, inscribir

        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["cocina", "citas"])
        registrar_venta(self.cajero, [{"variante": self.polo.pk, "cantidad": "1"}], [{"metodo": "EFE", "monto": "50"}])
        cli = Cliente.objects.create(nombre="Rosa", telefono="987000111")
        plan = Plan.objects.create(nombre="Mensual", precio=D("80"))
        ins = inscribir(cli, plan, self.cajero, inicio=self.hoy)
        cobrar(cli, [c.pk for c in ins.cuotas.all()], D("80"), "EFE", self.cajero)
        registrar_venta(self.cajero, [{"variante": self.polo.pk, "cantidad": "1"}], [{"metodo": "CRE", "monto": "50"}], cliente_id=cli.pk,
                        puede_fiar=True)
        registrar_abono(cli, D("20"), "EFE", self.cajero)
        rp = reporte(self.hoy, self.hoy, {"cobranzas", "clientes"})
        luis = next(f for f in rp["filas"] if f["nombre"] == "Luis")
        self.assertEqual((luis["ventas_n"], luis["cuotas"], luis["deudas"]), (2, D("80"), D("20")))
        self.assertEqual(luis["cobro"], D("200"))
        self.assertTrue(rp["ver"]["cuotas"] and rp["ver"]["deudas"])
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("reportes:inicio")), "pago de deuda")


class PagosTests(Base):
    """Pagos al personal: sueldo del periodo + comisión, menos lo pagado (de la caja o fuera de caja)."""

    def test_sueldo_del_periodo(self):
        from datetime import date

        from .pagos import sueldo_del_periodo

        p = Persona(nombre="X", sueldo=D("1500"), sueldo_cada="MES")
        self.assertEqual(sueldo_del_periodo(p, date(2026, 2, 1), date(2026, 2, 28)), D("1500"))
        self.assertEqual(sueldo_del_periodo(p, date(2026, 11, 1), date(2026, 11, 15)), D("750"))
        p.sueldo_cada = "QUI"
        p.sueldo = D("700")
        self.assertEqual(sueldo_del_periodo(p, date(2026, 11, 1), date(2026, 11, 30)), D("1400"))
        self.assertEqual(sueldo_del_periodo(p, date(2026, 11, 16), date(2026, 11, 30)), D("700"))
        p.sueldo_cada = "SEM"
        p.sueldo = D("350")
        self.assertEqual(sueldo_del_periodo(p, date(2026, 11, 2), date(2026, 11, 15)), D("700"))
        p.sueldo = D("0")
        self.assertEqual(sueldo_del_periodo(p, date(2026, 11, 2), date(2026, 11, 15)), D("0"))

    def test_cuenta_y_pantalla(self):
        from caja.models import MovimientoCaja, SesionCaja
        from caja.servicios import gasto_fuera_de_caja, movimiento

        from .pagos import cuentas, sueldo_del_periodo

        a = Ajustes.cargar()
        a.funciones_inactivas = []  # quién atendió, comisiones y pagos encendidos
        a.save()
        self.ana.sueldo, self.ana.sueldo_cada = D("900"), "MES"
        self.ana.save()
        Persona.objects.create(nombre="Sin sueldo")
        v = registrar_venta(self.cajero, [{"variante": self.polo.pk, "cantidad": "2"}], [{"metodo": "EFE", "monto": "100"}])
        v.atendio_persona = self.ana  # comisión: 10 % de 100
        v.save(update_fields=["atendio_persona"])
        s = SesionCaja.abierta_de(self.cajero)
        C = MovimientoCaja.Categoria
        movimiento(s, MovimientoCaja.Tipo.EGRESO, D("200"), "Adelanto", self.cajero, C.PERSONAL, persona=self.ana)
        gasto_fuera_de_caja(D("100"), "Yape", self.jefe, C.PERSONAL, persona=self.ana)
        c = cuentas(self.hoy, self.hoy)
        self.assertEqual([f["persona"] for f in c["filas"]], [self.ana])
        f = c["filas"][0]
        self.assertEqual(f["comision"], D("10"))
        self.assertEqual(f["sueldo"], sueldo_del_periodo(self.ana, self.hoy, self.hoy))
        self.assertEqual(f["pagado"], D("300"))
        self.assertEqual(f["pagos"], 2)
        self.assertEqual(f["falta"], f["sueldo"] + D("10") - D("300"))

        self.client.force_login(self.jefe)
        r = self.client.get(reverse("personal:pagos"))
        self.assertContains(r, "Pagó fuera de caja")
        self.assertContains(self.client.get(reverse("reportes:inicio")), "Pagos al personal")
        # la ficha pide el sueldo solo con la función encendida
        self.client.post(reverse("personal:persona", args=[self.ana.pk]),
                         {"nombre": "Ana", "color": "#0d6efd", "orden": 0, "activo": "on", "comision": "10", "sueldo": "1200", "sueldo_cada": "QUI"})
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.sueldo, self.ana.sueldo_cada), (D("1200"), "QUI"))
        # el egreso de la caja pide a quién
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("caja:egreso", args=[s.pk]), {"categoria": C.PERSONAL, "monto": "50", "concepto": "Pago"})
        self.assertContains(r, "Elige a quién")
        a.funciones_inactivas = ["atendio", "pagos"]
        a.save()
        self.assertNotIn("persona", self.client.get(reverse("caja:egreso", args=[s.pk])).context["form"].fields)
        self.client.force_login(self.jefe)
        self.assertRedirects(self.client.get(reverse("personal:pagos")), reverse("personal:lista"))
