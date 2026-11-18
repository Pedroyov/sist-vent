from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Ajustes, PermisosRol
from productos.models import Producto
from productos.servicios import asegurar_variante_unica

from personal.models import Persona

from .models import Ausencia, Cita, Config, Horario
from clientes.servicios import historial

from .servicios import (CitaError, Dia, a_esa_hora, agendar, atender, cancelar, no_vino, cerrar_pasadas, m, mensaje_cita, mensaje_horarios,
                        mis_horarios, proximos, reabrir)

D = Decimal


def _proximo(dia_semana):
    """La próxima fecha (desde mañana) que cae en ese día de la semana (0 = lunes)."""
    f = timezone.localdate() + timedelta(days=1)
    while f.weekday() != dia_semana:
        f += timedelta(days=1)
    return f


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": [], "rubro": "PEL", "nombre": "Salón Bella"})
        Config.objects.update_or_create(pk=1, defaults={"intervalo": 15, "duracion": 30})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.u_carla = User.objects.create_user("carla", password="x-clave-123")
        self.u_carla.groups.add(Group.objects.get(name="Profesional"))
        corte = Producto.objects.create(nombre="Corte", tipo=Producto.Tipo.SERVICIO, precio=D("25"), maneja_stock=False, duracion_min=30)
        tinte = Producto.objects.create(nombre="Tinte", tipo=Producto.Tipo.SERVICIO, precio=D("90"), maneja_stock=False, duracion_min=120)
        uñas = Producto.objects.create(nombre="Manicure", tipo=Producto.Tipo.SERVICIO, precio=D("20"), maneja_stock=False, duracion_min=40)
        self.corte, self.tinte, self.manicure = (asegurar_variante_unica(p) for p in (corte, tinte, uñas))
        self.carla = Persona.objects.create(nombre="Carla", usuario=self.u_carla)
        self.carla.servicios.set([corte, tinte])
        self.ana = Persona.objects.create(nombre="Ana")
        self.ana.servicios.set([uñas, corte])
        for p in (self.carla, self.ana):
            for d in range(6):
                Horario.objects.create(profesional=p, dia=d, entrada=time(9), salida=time(18), descanso_desde=time(13), descanso_hasta=time(14))
        self.lunes = _proximo(0)

    def cita(self, prof, hora, servicio=None, fecha=None, **kw):
        servicio = servicio or self.corte
        return agendar(self.cajero, profesional=prof, fecha=fecha or self.lunes, inicio=hora, duracion=servicio.producto.duracion_min,
                       servicio=servicio, nombre=kw.pop("nombre", "Carmen"), telefono=kw.pop("telefono", "987001122"), **kw)


class HorariosTests(Base):
    def test_libres_con_refrigerio_ausencia_y_citas(self):
        dia = Dia(self.lunes)
        self.assertEqual(dia.libres(self.carla), [(9 * 60, 13 * 60), (14 * 60, 18 * 60)])
        self.cita(self.carla, time(10))
        Ausencia.objects.create(profesional=self.carla, desde=self.lunes, hasta=self.lunes, hora_desde=time(16), hora_hasta=time(18), motivo="Permiso")
        dia = Dia(self.lunes)
        self.assertEqual(dia.libres(self.carla), [(9 * 60, 10 * 60), (10 * 60 + 30, 13 * 60), (14 * 60, 16 * 60)])
        # un tinte de 2 horas solo cabe donde hay 2 horas seguidas
        self.assertEqual(dia.horarios_libres(self.carla, 120, 15), [10 * 60 + 30, 10 * 60 + 45, 11 * 60, 14 * 60])
        self.assertEqual(Dia(self.lunes + timedelta(days=6)).libres(self.carla), [])  # domingo no trabaja

    def test_vacaciones(self):
        Ausencia.objects.create(profesional=self.carla, desde=self.lunes, hasta=self.lunes + timedelta(days=2), motivo="Vacaciones")
        dia = Dia(self.lunes)
        self.assertEqual(dia.libres(self.carla), [])
        self.assertEqual(dia.ausencia(self.carla).motivo, "Vacaciones")
        with self.assertRaisesMessage(CitaError, "no está libre"):
            self.cita(self.carla, time(10))

    def test_ocupada_recomienda_proxima_hora_y_otra_persona(self):
        self.cita(self.carla, time(9))
        with self.assertRaisesMessage(CitaError, "Carla no está libre"):
            self.cita(self.carla, time(9, 15), nombre="Otra")
        prox = proximos(self.carla, 30, self.lunes, m(time(9)), n=3)
        self.assertEqual(prox[0], (self.lunes, 9 * 60 + 30))
        otros = a_esa_hora(self.lunes, 9 * 60, 30, self.corte, sin=self.carla)
        self.assertEqual(otros, [(self.ana, 9 * 60)])
        self.assertEqual(a_esa_hora(self.lunes, 9 * 60, 120, self.tinte, sin=self.carla), [])  # Ana no hace tintes
        # quien gestiona puede agendar igual (cruzada)
        self.cita(self.carla, time(9, 15), nombre="Otra", forzar=True)

    def test_servicio_que_no_hace(self):
        with self.assertRaisesMessage(CitaError, "no hace"):
            self.cita(self.ana, time(10), servicio=self.tinte)

    def test_estados_y_reabrir(self):
        c = self.cita(self.carla, time(11))
        cancelar(c, self.cajero)
        otra = self.cita(self.carla, time(11), nombre="Otra")  # el horario quedó libre
        with self.assertRaisesMessage(CitaError, "ya se ocupó"):
            reabrir(c, self.cajero)
        atender(otra, self.cajero)
        reabrir(otra, self.cajero)
        self.assertEqual(otra.estado, Cita.Estado.CONFIRMADA)
        vieja = Cita.objects.create(fecha=timezone.localdate() - timedelta(days=1), inicio=time(9), fin=time(9, 30), profesional=self.ana,
                                    nombre="Ayer", creada_por=self.cajero)
        self.assertEqual(cerrar_pasadas(), 1)
        vieja.refresh_from_db()
        self.assertEqual(vieja.estado, Cita.Estado.NO_VINO)

    def test_preferido_y_mensajes(self):
        for i, d in enumerate((self.lunes, self.lunes + timedelta(days=1), self.lunes + timedelta(days=2))):
            atender(self.cita(self.carla if i < 2 else self.ana, time(10), fecha=d), self.cajero)
        h = historial("987 001 122")
        self.assertEqual((h["nombre"], h["citas"], h["preferido"]["nombre"], h["preferido"]["veces"]), ("Carmen", 3, "Carla", 2))
        c = self.cita(self.carla, time(15), nombre="Lucía", telefono="986")
        self.assertIn("con Carla en Salón Bella", mensaje_cita(c))
        self.assertIn("3:00 pm", mensaje_cita(c))
        texto = mensaje_horarios(self.carla, desde=self.lunes, dias=1)
        self.assertIn("9:00 am a 10:00 am", texto)
        self.assertIn("— Carla", texto)
        self.assertIn("*" + ("Hoy" if self.lunes == timezone.localdate() else "Mañana" if self.lunes == timezone.localdate() + timedelta(days=1) else "Lunes"), texto)
        self.assertEqual(mis_horarios(self.carla, desde=self.lunes, dias=1)[0][1][0], (9 * 60, 10 * 60))


class VistasTests(Base):
    def test_modulo_y_rol(self):
        from core.models import modulos_inactivos_iniciales

        self.assertIn("citas", modulos_inactivos_iniciales())
        self.assertIn("citas.mi_agenda", PermisosRol.objects.get(grupo__name="Profesional").permisos)

    def test_agenda_y_nueva_cita(self):
        self.client.force_login(self.cajero)
        self.cita(self.carla, time(10))
        resp = self.client.get(reverse("citas:agenda"), {"fecha": self.lunes.isoformat()})
        self.assertContains(resp, "agenda-cita")
        self.assertContains(resp, "Carmen")
        panel = self.client.get(reverse("citas:horarios"), {"servicio": self.corte.pk, "profesional": self.carla.pk,
                                                             "fecha": self.lunes.isoformat(), "hora": "10:00"})
        self.assertContains(panel, "Carla no está libre")
        self.assertContains(panel, "O a esa hora con")
        resp = self.client.post(reverse("citas:nueva"), {"servicio": self.corte.pk, "profesional": self.ana.pk, "fecha": self.lunes.isoformat(),
                                                         "hora": "10:00", "nombre": "Lucía", "telefono": "986002233"})
        c = Cita.objects.get(nombre="Lucía")
        self.assertRedirects(resp, reverse("citas:detalle", args=[c.pk]) + "?nueva=1", fetch_redirect_response=False)
        self.assertEqual((c.inicio, c.fin, c.servicio_nombre), (time(10), time(10, 30), "Corte"))
        # Atender y cobrar: lleva a Vender con el servicio
        resp = self.client.post(reverse("citas:accion", args=[c.pk, "atender"]), {"cobrar": "1"})
        self.assertRedirects(resp, f"{reverse('ventas:pos')}?citas={c.pk}", fetch_redirect_response=False)

    def test_profesional_ve_su_agenda_y_no_la_de_otros(self):
        mia = self.cita(self.carla, time(10))
        ajena = self.cita(self.ana, time(10), nombre="Otra")
        self.client.force_login(self.u_carla)
        self.assertRedirects(self.client.get(reverse("citas:agenda")), reverse("citas:mi_agenda"))
        resp = self.client.get(reverse("citas:mi_agenda"))
        self.assertContains(resp, "Compartir mis horarios")
        self.assertContains(resp, "wa.me/?text=")
        self.assertEqual(self.client.get(reverse("citas:detalle", args=[mia.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("citas:detalle", args=[ajena.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("citas:nueva")).status_code, 403)  # sin permiso de agendar
        self.client.post(reverse("citas:accion", args=[mia.pk, "atender"]))
        mia.refresh_from_db()
        self.assertEqual(mia.estado, Cita.Estado.ATENDIDA)

    def test_profesional_agenda_solo_las_suyas(self):
        pr = PermisosRol.objects.get(grupo__name="Profesional")
        pr.permisos = pr.permisos + ["citas.agendar_propias"]
        pr.save()
        self.client.force_login(self.u_carla)
        datos = {"servicio": self.corte.pk, "profesional": self.ana.pk, "fecha": self.lunes.isoformat(), "hora": "11:00", "nombre": "Amiga"}
        self.client.post(reverse("citas:nueva"), datos)
        self.assertEqual(Cita.objects.get(nombre="Amiga").profesional, self.carla)  # siempre con ella misma
        resp = self.client.post(reverse("citas:nueva"), {**datos, "nombre": "Cruce", "forzar": "1"})
        self.assertContains(resp, "no está libre")  # no puede forzar

    def test_vender_llega_con_el_servicio(self):
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse("ventas:pos"), {"agregar": f"{self.corte.pk},x"})
        self.assertEqual(resp.context["agregar"], [self.corte.pk])

    def test_personal_y_horarios(self):
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(jefe)
        datos = {"nombre": "Luis", "telefono": "", "usuario": "", "color": "#0d6efd", "orden": 0, "activo": "on", "atiende_citas": "on",
                 "h-TOTAL_FORMS": 7, "h-INITIAL_FORMS": 7, "h-MIN_NUM_FORMS": 7, "h-MAX_NUM_FORMS": 7}
        for d in range(7):
            if d in (1, 2):
                datos.update({f"h-{d}-trabaja": "on", f"h-{d}-entrada": "11:00", f"h-{d}-salida": "20:00",
                              f"h-{d}-descanso_desde": "15:00", f"h-{d}-descanso_hasta": "16:00"})
        resp = self.client.post(reverse("personal:nuevo"), datos)
        luis = Persona.objects.get(nombre="Luis")
        self.assertRedirects(resp, reverse("personal:persona", args=[luis.pk]))
        self.assertEqual(sorted(luis.horarios.values_list("dia", flat=True)), [1, 2])
        datos["h-1-salida"] = "10:00"  # salida antes de la entrada
        resp = self.client.post(reverse("personal:persona", args=[luis.pk]), datos)
        self.assertContains(resp, "La salida debe ser después de la entrada")
        resp = self.client.post(reverse("citas:ausencia", args=[luis.pk]), {"desde": self.lunes.isoformat(), "hasta": self.lunes.isoformat(),
                                                                            "motivo": "Vacaciones"})
        self.assertEqual(luis.ausencias.count(), 1)


class CobroTests(Base):
    def test_sin_cita_queda_por_cobrar_y_caja_lo_cobra(self):
        from caja.servicios import abrir

        from .servicios import por_cobrar, registrar_servicios

        self.client.force_login(self.u_carla)
        resp = self.client.post(reverse("citas:registrar"), {f"s{self.corte.pk}": "1", f"s{self.tinte.pk}": "1", "nombre": "Lucía",
                                                             "telefono": "986002233", "profesional": self.ana.pk})
        self.assertRedirects(resp, reverse("citas:mi_agenda"))
        hechas = list(Cita.objects.filter(nombre="Lucía").order_by("inicio"))
        self.assertEqual([c.profesional for c in hechas], [self.carla, self.carla])  # siempre ella misma
        self.assertTrue(all(c.sin_cita and c.por_cobrar for c in hechas))
        self.assertEqual(hechas[0].fin, hechas[1].inicio)  # uno tras otro
        g = por_cobrar()
        self.assertEqual((len(g), g[0]["total"]), (1, D("115")))
        # caja: Vender llega con los dos servicios y, al cobrar, salen de «por cobrar»
        abrir(self.cajero, D("0"))
        self.client.force_login(self.cajero)
        ids = ",".join(str(c.pk) for c in hechas)
        resp = self.client.get(reverse("ventas:pos"), {"citas": ids})
        self.assertEqual(sorted(resp.context["agregar"]), sorted([self.corte.pk, self.tinte.pk]))
        self.assertContains(resp, "Cobrando: <strong>Lucía")
        import json

        datos = {"items": [{"variante": self.corte.pk, "cantidad": "1"}, {"variante": self.tinte.pk, "cantidad": "1"}],
                 "pagos": [{"metodo": "EFE", "monto": "115"}], "citas": [c.pk for c in hechas], "token": "t-1"}
        r = self.client.post(reverse("ventas:registrar"), json.dumps(datos), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(por_cobrar(), [])
        self.assertTrue(all(c.venta_id for c in Cita.objects.filter(nombre="Lucía")))
        # algo más en una cita ya atendida
        c = self.cita(self.carla, time(10))
        atender(c, self.cajero)
        extra = registrar_servicios(self.u_carla, self.carla, [self.corte], cita=c)
        self.assertEqual((extra[0].nombre, extra[0].inicio, extra[0].sin_cita), ("Carmen", c.fin, False))
        with self.assertRaisesMessage(CitaError, "Marca al menos"):
            registrar_servicios(self.u_carla, self.carla, [])

    def test_atender_y_cobrar_y_ya_cobrado(self):
        self.client.force_login(self.cajero)
        c = self.cita(self.carla, time(10))
        resp = self.client.post(reverse("citas:accion", args=[c.pk, "atender"]), {"cobrar": "1"})
        self.assertRedirects(resp, f"{reverse('ventas:pos')}?citas={c.pk}", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("citas:por_cobrar")), "Carmen")
        self.client.post(reverse("citas:cobrada_aparte"), {"ids": str(c.pk)})
        c.refresh_from_db()
        self.assertTrue(c.cobrada)
        with self.assertRaisesMessage(CitaError, "ya se cobró"):
            reabrir(c, self.cajero)


class ReporteTests(Base):
    def test_quien_atiende_y_comisiones(self):
        from personal.reportes import reporte

        from .servicios import registrar_servicios

        a = Ajustes.cargar()
        a.funciones_inactivas = []
        a.save()
        self.carla.comision = D("40")
        self.carla.save()
        atender(self.cita(self.carla, time(10)), self.cajero)
        atender(self.cita(self.carla, time(11), servicio=self.tinte, nombre="Lucía", telefono="986"), self.cajero)
        no_vino(self.cita(self.ana, time(10), nombre="Otra", telefono="985"), self.cajero)
        registrar_servicios(self.cajero, self.ana, [self.manicure], "Paola")
        hoy = timezone.localdate()
        r = reporte(min(hoy, self.lunes), max(hoy, self.lunes), {"citas"}, comisiones=True)
        carla = next(g for g in r["filas"] if g["persona"] == self.carla)
        ana = next(g for g in r["filas"] if g["persona"] == self.ana)
        self.assertEqual((carla["servicios"], carla["generado"], carla["clientes"], carla["comision"]), (2, D("115"), 2, D("46.00")))
        self.assertEqual((ana["servicios"], ana["sin_cita"], ana["no_vino"], ana["comision"]), (1, 1, 1, D("0.00")))
        self.assertEqual(r["filas"][0]["persona"], self.carla)  # la que más generó primero
        self.assertEqual({f["servicio"] for f in r["tabla"]}, {"Corte", "Tinte", "Manicure"})
        # en Reportes y en Mi agenda
        jefe = User.objects.create_user("jefe", password="x-clave-123")
        jefe.groups.add(Group.objects.get(name="Administración"))
        self.client.force_login(jefe)
        resp = self.client.get(reverse("reportes:inicio"), {"desde": min(hoy, self.lunes).isoformat(), "hasta": max(hoy, self.lunes).isoformat()})
        self.assertContains(resp, "Servicios por persona")
        self.assertContains(resp, "Comisiones a pagar")
        self.assertEqual(self.client.get(reverse("reportes:inicio"), {"excel": 1}).status_code, 200)
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["citas"], funciones_inactivas=["comisiones"])
        resp = self.client.get(reverse("reportes:inicio"))
        self.assertNotContains(resp, "Servicios por persona")
        self.assertNotContains(resp, "Comisiones a pagar")

    def test_precio_cobrado(self):
        from caja.servicios import abrir

        from .servicios import marcar_cobradas
        from ventas.servicios import registrar_venta

        c = self.cita(self.carla, time(10))
        atender(c, self.cajero)
        abrir(self.cajero, D("0"))
        v = registrar_venta(self.cajero, [{"variante": self.corte.pk, "cantidad": "1", "precio": "20"}], [{"metodo": "EFE", "monto": "20"}],
                            puede_cambiar_precio=True)
        marcar_cobradas([c.pk], v)
        c.refresh_from_db()
        self.assertEqual((c.precio, c.cobrada), (D("20.00"), True))
