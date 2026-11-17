from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Ajustes
from mesas.models import Cuenta, Mesa, Zona
from mesas.servicios import abrir_cuenta

from .models import Config, Reserva
from .servicios import (ReservaError, atrasadas, cancelar, cerrar_pasadas, confirmar, guardar, historial, llego, mensaje, no_vino, para_mapa,
                        reabrir)


def _en(fecha, hh, mm=0):
    return timezone.make_aware(datetime.combine(fecha, time(hh, mm)))


class Base(TestCase):
    def setUp(self):
        Ajustes.objects.update_or_create(pk=1, defaults={"modulos_inactivos": ["cocina"], "rubro": "RES", "nombre": "La Buena Mesa"})
        self.cajero = User.objects.create_user("cajero", password="x-clave-123")
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.mozo = User.objects.create_user("mozo", password="x-clave-123")
        self.mozo.groups.add(Group.objects.get(name="Mozo"))
        z = Zona.objects.create(nombre="Salón")
        self.m1 = Mesa.objects.create(zona=z, nombre="1", capacidad=4)
        self.m2 = Mesa.objects.create(zona=z, nombre="2", capacidad=2)
        self.manana = timezone.localdate() + timedelta(days=1)

    def reservar(self, fecha=None, hora=time(20, 0), mesa=None, personas=4, nombre="Familia Pérez", telefono="987654321", **kw):
        r, _ = guardar(self.cajero, fecha=fecha or self.manana, hora=hora, personas=personas, nombre=nombre, telefono=telefono, mesa=mesa, **kw)
        return r


class ServiciosTests(Base):
    def test_crear_y_choque_de_mesa(self):
        r = self.reservar(mesa=self.m1)
        self.assertEqual(r.estado, Reserva.Estado.PENDIENTE)
        self.assertEqual(r.cliente.telefono, "987654321")  # queda en clientes
        with self.assertRaisesMessage(ReservaError, "ya está reservada"):
            self.reservar(hora=time(21, 0), mesa=self.m1, nombre="Otro")
        self.reservar(hora=time(21, 0), mesa=self.m1, nombre="Otro", permitir_choque=True)  # se puede si se confirma
        self.reservar(hora=time(23, 0), mesa=self.m1, nombre="Tarde")  # dos horas después de la de las 21: no choca
        cancelar(r, self.cajero)
        self.reservar(hora=time(20, 30), mesa=self.m2, nombre="Mesa chica", personas=2)
        _, avisos = guardar(self.cajero, fecha=self.manana, hora=time(13, 0), personas=6, nombre="Grupo", mesa=self.m2)
        self.assertIn("es para 2", avisos[0])

    def test_validaciones(self):
        with self.assertRaisesMessage(ReservaError, "nombre"):
            self.reservar(nombre="  ")
        with self.assertRaisesMessage(ReservaError, "ya pasaron"):
            self.reservar(fecha=timezone.localdate() - timedelta(days=1))
        with self.assertRaisesMessage(ReservaError, "personas"):
            self.reservar(personas=0)

    def test_estados(self):
        r = self.reservar()
        confirmar(r, self.cajero)
        with self.assertRaises(ReservaError):
            confirmar(r, self.cajero)
        no_vino(r, self.cajero)
        with self.assertRaisesMessage(ReservaError, "ya se cerró"):
            guardar(self.cajero, r, fecha=r.fecha, hora=r.hora, personas=2, nombre="x")
        reabrir(r, self.cajero)
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(historial("987654321")["reservas"], 1)

    def test_llegaron_abre_la_mesa(self):
        r = self.reservar(fecha=timezone.localdate(), hora=time(23, 30), mesa=self.m1)
        c = llego(r, self.mozo)
        self.assertEqual((c.mesa, c.personas, c.nombre), (self.m1, 4, "Familia Pérez"))
        self.assertEqual(c.cliente, r.cliente)
        r.refresh_from_db()
        self.assertEqual((r.estado, r.cuenta), (Reserva.Estado.LLEGO, c))
        # mesa ocupada: pide otra
        r2 = self.reservar(fecha=timezone.localdate(), hora=time(23, 45), mesa=self.m1, nombre="Otro",
                           permitir_choque=True)
        with self.assertRaisesMessage(ReservaError, "Elige otra mesa"):
            llego(r2, self.mozo)
        self.assertEqual(llego(r2, self.mozo, self.m2).mesa, self.m2)
        # sin mesa asignada hay que elegirla
        r3 = self.reservar(fecha=timezone.localdate(), hora=time(23, 45), nombre="Sin mesa")
        with self.assertRaisesMessage(ReservaError, "Elige la mesa"):
            llego(r3, self.mozo)

    def test_sin_modulo_mesas_solo_marca(self):
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["mesas", "cocina"])
        r = self.reservar()
        self.assertIsNone(llego(r, self.cajero))
        self.assertEqual(r.estado, Reserva.Estado.LLEGO)

    def test_mapa_atrasadas_y_pasadas(self):
        hoy = timezone.localdate()
        r = Reserva.objects.create(fecha=hoy, hora=time(20, 0), personas=4, nombre="Pérez", mesa=self.m1, creada_por=self.cajero)
        Config.objects.update_or_create(pk=1, defaults={"antes": 60, "tolerancia": 20})
        self.assertEqual(para_mapa(_en(hoy, 18, 50)), {})
        self.assertEqual(para_mapa(_en(hoy, 19, 5)), {self.m1.pk: r})
        self.assertEqual(para_mapa(_en(hoy, 20, 15)), {self.m1.pk: r})
        self.assertEqual(para_mapa(_en(hoy, 20, 25)), {})
        self.assertEqual(atrasadas(_en(hoy, 20, 25)), [r])
        vieja = Reserva.objects.create(fecha=hoy - timedelta(days=1), hora=time(20, 0), personas=2, nombre="Ayer", creada_por=self.cajero)
        self.assertEqual(cerrar_pasadas(), 1)
        vieja.refresh_from_db()
        self.assertEqual(vieja.estado, Reserva.Estado.NO_VINO)

    def test_mensaje_whatsapp(self):
        r = self.reservar(hora=time(20, 30))
        texto = mensaje(r)
        self.assertIn("le confirmamos su reserva en La Buena Mesa para mañana a las 8:30 pm, 4 personas", texto)
        r.fecha = timezone.localdate()
        self.assertIn("reserva de hoy a las 8:30 pm", mensaje(r))


class VistasTests(Base):
    def test_modulo_apagado_por_defecto_en_instalacion_nueva(self):
        from core.models import modulos_inactivos_iniciales

        self.assertIn("reservas", modulos_inactivos_iniciales())

    def test_agenda_y_permisos(self):
        self.client.force_login(self.mozo)
        self.assertEqual(self.client.get(reverse("reservas:agenda")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reservas:nueva")).status_code, 403)  # el mozo no toma reservas
        Ajustes.objects.filter(pk=1).update(modulos_inactivos=["cocina", "reservas"])
        self.assertEqual(self.client.get(reverse("reservas:agenda")).status_code, 403)

    def test_tomar_reserva_y_llegar_desde_el_mapa(self):
        self.client.force_login(self.cajero)
        hora = (timezone.localtime() + timedelta(minutes=30)).strftime("%H:%M")
        hoy = timezone.localdate()
        if (timezone.localtime() + timedelta(minutes=30)).date() != hoy:
            return
        resp = self.client.post(reverse("reservas:nueva"), {"fecha": hoy.isoformat(), "hora": hora, "personas": 3, "nombre": "Carla",
                                                            "telefono": "986111222", "mesa": self.m1.pk, "nota": "ventana"})
        self.assertEqual(resp.status_code, 302)
        r = Reserva.objects.get()
        mapa = self.client.get(reverse("mesas:mapa"))
        self.assertContains(mapa, "mesa reservada")
        self.assertContains(mapa, "Reservas de hoy:")
        self.client.force_login(self.mozo)
        resp = self.client.post(reverse("reservas:accion", args=[r.pk, "llego"]), {"mesa": self.m1.pk})
        c = Cuenta.objects.get(mesa=self.m1, estado=Cuenta.Estado.ABIERTA)
        self.assertRedirects(resp, reverse("mesas:cuenta", args=[c.pk]))
        self.assertEqual(c.personas, 3)
        # el mozo no puede cancelar ni confirmar
        r2 = self.reservar()
        self.assertEqual(self.client.post(reverse("reservas:accion", args=[r2.pk, "cancelar"])).status_code, 403)

    def test_choque_pide_confirmar(self):
        self.reservar(mesa=self.m1)
        self.client.force_login(self.cajero)
        datos = {"fecha": self.manana.isoformat(), "hora": "20:30", "personas": 2, "nombre": "Otro", "mesa": self.m1.pk}
        resp = self.client.post(reverse("reservas:nueva"), datos)
        self.assertContains(resp, "Reservar igual esa mesa")
        resp = self.client.post(reverse("reservas:nueva"), {**datos, "permitir_choque": "True"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Reserva.objects.count(), 2)

    def test_inicio_muestra_reservas(self):
        hoy = timezone.localdate()
        Reserva.objects.create(fecha=hoy, hora=time(0, 0), personas=2, nombre="Madrugador", creada_por=self.cajero)  # atrasada
        self.reservar()
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse("core:inicio"))
        self.assertContains(resp, "Reservas de hoy")
        self.assertContains(resp, "sin llegar: Madrugador")
        self.assertContains(resp, "por confirmar")

    def test_historial_por_celular(self):
        r = self.reservar()
        no_vino(r, self.cajero)
        self.client.force_login(self.cajero)
        d = self.client.get(reverse("reservas:historial"), {"tel": "987 654 321"}).json()
        self.assertEqual((d["nombre"], d["reservas"], d["no_vino"]), ("Familia Pérez", 1, 1))
