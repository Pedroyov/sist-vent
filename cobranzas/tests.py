from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.servicios import abrir, calcular, cerrar
from clientes.models import Cliente
from core.models import Ajustes

from .models import Config, Cuota, Inscripcion, Plan
from .servicios import (CobranzaError, adelantar, al_dia, anular_pago, cambiar_precio, cobrar, dar_baja, exonerar, generar,
                        inscribir, mensaje, pendientes, quitar_mora, reactivar, resumen, sumar_meses, vencidas)

D = Decimal


def activar():
    a = Ajustes.cargar()
    a.modulos_inactivos = []
    a.save()


class Base(TestCase):
    def setUp(self):
        activar()
        self.hoy = timezone.localdate()
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.vendedor = User.objects.create_user("vendedor", password="x-clave-123")
        self.vendedor.groups.add(Group.objects.get(name="Vendedor"))
        self.jefe = User.objects.create_user("jefe", password="x-clave-123")
        self.jefe.groups.add(Group.objects.get(name="Administración"))
        self.caja = abrir(self.cajero, D("50"))
        self.gym = Plan.objects.create(nombre="Gimnasio mensual", precio=D("90"))
        self.ingles = Plan.objects.create(nombre="Inglés básico", precio=D("150"), num_cuotas=6, matricula=D("50"))
        self.taller = Plan.objects.create(nombre="Taller de verano", precio=D("200"), frecuencia=Plan.Frecuencia.UNICO)
        self.ana = Cliente.objects.create(tipo_documento="DNI", numero_documento="45123678", nombre="Ana Torres", telefono="987654321")


class CuotasTests(Base):
    def test_fechas_de_las_cuotas(self):
        self.assertEqual(sumar_meses(date(2026, 1, 31), 1, 31), date(2026, 2, 28))
        self.assertEqual(sumar_meses(date(2026, 11, 15), 2, 5), date(2027, 1, 5))
        insc = inscribir(self.ana, self.gym, self.cajero, inicio=date(2026, 1, 31))
        fechas = list(insc.cuotas.values_list("vence", flat=True)[:3])
        self.assertEqual(fechas, [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])
        self.assertEqual(insc.cuotas.first().concepto, "Mensualidad ene. 2026")

    def test_plan_sin_fin_genera_hasta_hoy_y_lo_que_vence_pronto(self):
        inicio = sumar_meses(self.hoy, -3, self.hoy.day)
        insc = inscribir(self.ana, self.gym, self.cajero, inicio=inicio)
        # 4 cuotas: hace 3, 2 y 1 mes y la de este mes (la del mes siguiente aún no)
        self.assertEqual(insc.cuotas.count(), 4)
        self.assertEqual(vencidas().count(), 3)
        self.assertEqual(generar(insc), 0)  # no duplica
        # con el paso del tiempo, al_dia() genera la siguiente sola
        with mock.patch("django.utils.timezone.localdate", return_value=sumar_meses(self.hoy, 1, self.hoy.day)):
            al_dia()
        self.assertEqual(insc.cuotas.count(), 5)
        self.assertEqual(adelantar(insc, 2), 2)
        self.assertEqual(insc.cuotas.count(), 7)

    def test_curso_con_matricula_y_cuotas_fijas(self):
        insc = inscribir(self.ana, self.ingles, self.cajero, alumno="Luis Torres")
        self.assertEqual(list(insc.cuotas.values_list("concepto", flat=True))[:2], ["Matrícula", "Cuota 1 de 6"])
        self.assertEqual(insc.cuotas.count(), 7)
        self.assertEqual(insc.quien, "Luis Torres")
        with self.assertRaisesMessage(CobranzaError, "ya está inscrito"):
            inscribir(self.ana, self.ingles, self.cajero, alumno="luis   torres".title())
        sin_mat = inscribir(self.ana, self.ingles, self.cajero, alumno="Sofía", cobrar_matricula=False, precio="120")
        self.assertEqual(sin_mat.cuotas.count(), 6)
        self.assertEqual(sin_mat.cuotas.first().monto, D("120"))
        unico = inscribir(self.ana, self.taller, self.cajero)
        self.assertEqual(list(unico.cuotas.values_list("concepto", "monto")), [("Taller de verano", D("200"))])


class CobroTests(Base):
    def test_cobro_parcial_en_orden_y_caja(self):
        insc = inscribir(self.ana, self.ingles, self.cajero)  # matrícula 50 + 6 × 150
        mat, c1, c2 = insc.cuotas.all()[:3]
        with self.assertRaisesMessage(CobranzaError, "suman S/ 200.00"):
            cobrar(self.ana, [c1.pk, mat.pk], "250", "EFE", self.cajero)
        with self.assertRaisesMessage(CobranzaError, "Método"):
            cobrar(self.ana, [c1.pk], "10", "CRE", self.cajero)
        p = cobrar(self.ana, [c1.pk, mat.pk], "120", "EFE", self.cajero)
        mat.refresh_from_db()
        c1.refresh_from_db()
        self.assertEqual((mat.pagado, c1.pagado, c1.estado), (D("50"), D("70"), "parcial"))  # primero la más antigua
        self.assertEqual(p.detalles.count(), 2)
        cobrar(self.ana, [c1.pk, c2.pk], "100", "YAP", self.cajero)
        r = calcular(self.caja)
        self.assertEqual((r["cuotas"], r["cuotas_efectivo"], r["esperado"]), (D("220"), D("120"), D("170")))
        # anular devuelve la deuda y saca el efectivo de la caja
        anular_pago(p, self.jefe, "error de digitación")
        mat.refresh_from_db()
        self.assertEqual(mat.pagado, D("0"))
        self.assertEqual(calcular(self.caja)["esperado"], D("50"))
        with self.assertRaisesMessage(CobranzaError, "ya estaba anulado"):
            anular_pago(p, self.jefe, "otra vez")

    def test_anular_con_caja_cerrada_sale_de_la_caja_abierta(self):
        insc = inscribir(self.ana, self.gym, self.cajero)
        p = cobrar(self.ana, [insc.cuotas.first().pk], "90", "EFE", self.cajero)
        cerrar(self.caja, D("140"), self.cajero)
        nueva = abrir(self.cajero, D("0"))
        anular_pago(p, self.cajero, "se devolvió")
        self.assertEqual(calcular(nueva)["egresos"], D("90"))

    def test_sin_caja_no_cobra(self):
        insc = inscribir(self.ana, self.gym, self.vendedor)
        with self.assertRaisesMessage(CobranzaError, "Abre tu caja"):
            cobrar(self.ana, [insc.cuotas.first().pk], "90", "EFE", self.vendedor)

    def test_plan_fijo_termina_al_pagar_todo(self):
        insc = inscribir(self.ana, self.taller, self.cajero)
        p = cobrar(self.ana, list(insc.cuotas.values_list("pk", flat=True)), "200", "TAR", self.cajero)
        insc.refresh_from_db()
        self.assertEqual(insc.estado, Inscripcion.Estado.TERMINADA)
        anular_pago(p, self.jefe, "tarjeta rechazada")
        insc.refresh_from_db()
        self.assertEqual(insc.estado, Inscripcion.Estado.ACTIVA)


class ReglasTests(Base):
    def test_baja_y_reactivar(self):
        insc = inscribir(self.ana, self.gym, self.cajero, inicio=sumar_meses(self.hoy, -1, self.hoy.day))
        adelantar(insc, 2)
        self.assertEqual(insc.cuotas.count(), 4)
        n = dar_baja(insc, self.cajero, "se mudó")
        self.assertEqual(n, 2)  # las adelantadas se quitan; lo vencido se sigue debiendo
        self.assertEqual(sum(c.pendiente for c in insc.cuotas.all()), D("180"))
        self.assertEqual(generar(insc), 0)
        reactivar(insc)
        self.assertEqual(sum(c.pendiente for c in insc.cuotas.all()), D("360"))

    def test_mora_opcional_y_perdon(self):
        inscribir(self.ana, self.gym, self.cajero, inicio=self.hoy - timedelta(days=10))
        al_dia()
        self.assertFalse(Cuota.objects.filter(mora__gt=0).exists())  # apagada por defecto
        cfg = Config.cargar()
        cfg.mora_activa, cfg.mora_monto, cfg.dias_gracia = True, D("5"), 3
        cfg.save()
        al_dia()
        al_dia()
        c = Cuota.objects.get(numero=1)
        self.assertEqual((c.mora, c.pendiente), (D("5"), D("95")))
        quitar_mora(c)
        al_dia()
        c.refresh_from_db()
        self.assertEqual((c.mora, c.mora_perdonada), (D("0"), True))

    def test_exonerar_y_cambiar_precio(self):
        insc = inscribir(self.ana, self.ingles, self.cajero)
        mat = insc.cuotas.get(numero=0)
        with self.assertRaisesMessage(CobranzaError, "motivo"):
            exonerar(mat, self.jefe, "")
        exonerar(mat, self.jefe, "promoción")
        self.assertEqual(pendientes(self.ana).count(), 6)
        self.assertEqual(cambiar_precio(insc, "100"), 6)  # las 6 cuotas: ninguna vencida ni pagada
        self.assertTrue(insc.cuotas.filter(numero=6, monto=D("100")).exists())

    def test_resumen_y_mensaje(self):
        insc = inscribir(self.ana, self.gym, self.cajero, inicio=sumar_meses(self.hoy, -1, self.hoy.day), alumno="Luis")
        r = resumen()
        self.assertEqual((r["vencido"], r["morosos"], r["activos"]), (D("90"), 1, 1))
        texto = mensaje(self.ana, list(pendientes(self.ana)))
        self.assertIn("Hola Ana", texto)
        self.assertIn("de Luis", texto)
        self.assertIn("Total: S/ 180.00", texto)
        self.assertEqual(insc.cuotas.count(), 2)


class VistasTests(Base):
    def test_flujo_completo_por_pantallas(self):
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get(reverse("cobranzas:inicio")).status_code, 200)
        r = self.client.post(reverse("cobranzas:inscribir"), {
            "nombre": "Pedro Ríos", "documento": "41239876", "telefono": "986111222", "alumno": "Mateo Ríos",
            "plan": self.ingles.pk, "inicio": self.hoy.isoformat(), "cobrar_matricula": "on"})
        pedro = Cliente.objects.get(numero_documento="41239876")
        self.assertRedirects(r, reverse("cobranzas:cuenta", args=[pedro.pk]))
        self.assertEqual(pedro.telefono, "986111222")
        r = self.client.get(reverse("cobranzas:cuenta", args=[pedro.pk]))
        self.assertContains(r, "Mateo Ríos")
        self.assertContains(r, 'form="f-cobro"')  # celular: monto y Cobrar en la barra fija
        self.assertContains(r, "wa.me/51986111222")
        ids = list(pendientes(pedro).values_list("pk", flat=True)[:2])
        r = self.client.post(reverse("cobranzas:cobrar", args=[pedro.pk]), {"cuota": ids, "monto": "200", "metodo": "EFE"})
        pago = pedro.pagos_cobranza.get()
        self.assertRedirects(r, reverse("cobranzas:cuenta", args=[pedro.pk]) + f"?recibo={pago.pk}", fetch_redirect_response=False)
        r = self.client.get(reverse("cobranzas:recibo", args=[pago.pk]))
        self.assertContains(r, "RECIBO DE PAGO")
        self.assertContains(r, "Matrícula")
        for nombre in ("morosos", "inscritos"):
            self.assertEqual(self.client.get(reverse(f"cobranzas:{nombre}")).status_code, 200)
            r = self.client.get(reverse(f"cobranzas:{nombre}") + "?excel=1")
            self.assertEqual(r["Content-Type"][:30], "application/vnd.openxmlformats")
        self.assertContains(self.client.get(reverse("cobranzas:buscar") + "?q=mateo"), "Pedro Ríos")
        self.assertNotContains(self.client.get(reverse("caja:sesion", args=[self.caja.pk])), "Cobrado de cuotas")  # cierre ciego
        self.client.force_login(self.jefe)
        self.assertContains(self.client.get(reverse("caja:sesion", args=[self.caja.pk])), "Cobrado de cuotas")
        self.client.force_login(self.cajero)
        self.assertContains(self.client.get(reverse("clientes:detalle", args=[pedro.pk])), "Inglés básico")
        self.assertContains(self.client.get(reverse("core:inicio")), "Cobranzas")
        # el cajero no gestiona: planes, reporte y anular no
        self.assertEqual(self.client.get(reverse("cobranzas:planes")).status_code, 403)
        self.assertEqual(self.client.post(reverse("cobranzas:anular", args=[pago.pk]), {"motivo": "x"}).status_code, 403)

    def test_gestion_y_permisos(self):
        self.client.force_login(self.jefe)
        r = self.client.post(reverse("cobranzas:plan_nuevo"), {"nombre": "Natación", "precio": "120", "frecuencia": "MEN",
                                                               "num_cuotas": "0", "matricula": "0", "activo": "on", "orden": "0"})
        self.assertRedirects(r, reverse("cobranzas:planes"))
        r = self.client.post(reverse("cobranzas:configurar"), {"dias_aviso": "5", "mora_activa": "on", "mora_monto": "10", "dias_gracia": "2"})
        self.assertTrue(Config.cargar().cobra_mora)
        insc = inscribir(self.ana, self.gym, self.cajero)
        cuota = insc.cuotas.first()
        self.client.post(reverse("cobranzas:accion_cuota", args=[cuota.pk, "exonerar"]), {"motivo": "beca"})
        cuota.refresh_from_db()
        self.assertTrue(cuota.anulada)
        self.client.post(reverse("cobranzas:accion_inscripcion", args=[insc.pk, "baja"]), {"motivo": ""})
        insc.refresh_from_db()
        self.assertEqual(insc.estado, Inscripcion.Estado.BAJA)
        self.assertEqual(self.client.get(reverse("cobranzas:reporte") + f"?mes={self.hoy:%Y-%m}").status_code, 200)
        # el vendedor ve, pero no cobra
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(reverse("cobranzas:cuenta", args=[self.ana.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("cobranzas:cobrar", args=[self.ana.pk]), {}).status_code, 403)

    def test_modulo_apagado(self):
        a = Ajustes.cargar()
        a.modulos_inactivos = ["cobranzas"]
        a.save()
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(reverse("cobranzas:inicio")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("core:inicio")), reverse("cobranzas:inicio"))
        # sin Clientes, Cobranzas también se apaga
        a.modulos_inactivos = ["clientes"]
        a.save()
        self.assertEqual(self.client.get(reverse("cobranzas:inicio")).status_code, 403)
