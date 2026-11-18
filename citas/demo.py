"""Personal y citas de ejemplo para la peluquería (python manage.py datos_demo --rubro PEL).

Cuatro personas con horarios distintos (una con vacaciones), citas de hoy alrededor de la hora actual, de los próximos
días e historial (así se ve «suele atenderse con …»). El usuario «estilista» (clave demo1234) es Carla: ve su agenda.
"""
import random
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from productos.models import Producto, Variante

from personal.models import Persona

from .models import Ausencia, Cita, Horario
from .servicios import Dia, a_hora, duracion_de

CLIENTES = [("Carmen Ruiz", "987001122"), ("Lucía Paredes", "986002233"), ("Milagros Soto", "985003344"), ("Sofía Ramírez", "984004455"),
            ("Andrea Cáceres", "983005566"), ("Valeria Núñez", "982006677"), ("Rocío Flores", "981007788"), ("Jimena Vela", "980008899"),
            ("Martín Gómez", "979009900"), ("Renzo Aguilar", "978001212")]


def _h(txt):
    hh, mm = txt.split(":")
    return time(int(hh), int(mm))


def cargar_citas():
    from core.permisos import PROFESIONAL

    rnd = random.Random(11)
    User = get_user_model()
    estilista, nuevo = User.objects.get_or_create(username="estilista", defaults={"first_name": "Carla", "last_name": "Mendoza Ríos"})
    estilista.set_password("demo1234")
    estilista.save()
    estilista.groups.add(Group.objects.get(name=PROFESIONAL))
    cajero = User.objects.filter(username="cajero").first() or User.objects.filter(is_superuser=True).first()
    serv = {p.nombre: p for p in Producto.objects.filter(tipo=Producto.Tipo.SERVICIO)}

    def nuevo_prof(nombre, color, servicios, dias, usuario=None, orden=0):
        p = Persona.objects.create(atiende_citas=True, nombre=nombre, color=color, usuario=usuario, orden=orden, telefono=f"9{rnd.randint(10000000, 99999999)}")
        p.servicios.set([serv[s] for s in servicios if s in serv])
        for d, (ent, sal, dd, dh) in dias.items():
            Horario.objects.create(profesional=p, dia=d, entrada=_h(ent), salida=_h(sal), descanso_desde=_h(dd) if dd else None,
                                   descanso_hasta=_h(dh) if dh else None)
        return p

    semana = {d: ("09:00", "19:00", "13:00", "14:00") for d in range(5)}
    semana[5] = ("09:00", "15:00", None, None)
    carla = nuevo_prof("Carla", "#d63384", ["Corte de cabello", "Tinte completo"], semana, estilista, 1)
    ana = nuevo_prof("Ana", "#6f42c1", ["Manicure", "Pedicure"], {d: v for d, v in semana.items() if d != 0}, orden=2)
    rosa = nuevo_prof("Rosa", "#20c997", [], {d: ("10:00", "20:00", "14:00", "15:00") for d in range(6)}, orden=3)
    luis = nuevo_prof("Luis", "#0d6efd", ["Corte de cabello", "Corte + barba"],
                      {d: ("11:00", "21:00", "15:00", "16:00") for d in range(1, 7)}, orden=4)
    from decimal import Decimal

    from core.models import Ajustes

    a = Ajustes.cargar()  # la demo muestra las comisiones (en un negocio real vienen apagadas)
    a.funciones_inactivas = [f for f in (a.funciones_inactivas or []) if f != "comisiones"]
    a.save(update_fields=["funciones_inactivas"])
    for p, pct in ((carla, 40), (ana, 35), (rosa, 40), (luis, 35)):
        p.comision = Decimal(pct)
        p.save(update_fields=["comision"])
    hoy = timezone.localdate()
    Ausencia.objects.create(profesional=rosa, desde=hoy + timedelta(days=2), hasta=hoy + timedelta(days=6), motivo="Vacaciones")
    Ausencia.objects.create(profesional=carla, desde=hoy + timedelta(days=1), hasta=hoy + timedelta(days=1), hora_desde=_h("09:00"),
                            hora_hasta=_h("11:00"), motivo="Entra tarde")

    variantes = {}
    for v in Variante.objects.filter(producto__tipo=Producto.Tipo.SERVICIO, activa=True).select_related("producto"):
        variantes.setdefault(v.producto.nombre, []).append(v)
    gente = list(CLIENTES)
    turno = [0]

    def siguiente():
        turno[0] += 1
        return gente[turno[0] % len(gente)]

    def agendar_en(prof, fecha, desde_min, estado, quien=None, max_citas=None):
        """Pone una cita en el primer hueco libre del profesional desde esa hora."""
        nombres = [s.nombre for s in prof.servicios.all()] or list(variantes)
        v = rnd.choice(variantes[rnd.choice([n for n in nombres if n in variantes])])
        dur = duracion_de(v)
        dia = Dia(fecha)
        libres = [t for t in dia.horarios_libres(prof, dur, 15, ahora=timezone.now() - timedelta(days=30)) if t >= desde_min]
        if not libres:
            return None
        t = libres[0]
        nombre, tel = quien or siguiente()
        return Cita.objects.create(fecha=fecha, inicio=a_hora(t), fin=a_hora(t + dur), profesional=prof, servicio=v,
                                   servicio_nombre=v.nombre_completo, precio=v.precio_venta, nombre=nombre, telefono=tel, estado=estado, creada_por=cajero,
                                   cobrada=estado == Cita.Estado.ATENDIDA,
                                   creada_en=timezone.now() - timedelta(days=rnd.randint(1, 5)))

    ahora = timezone.localtime()
    min_ahora = ahora.hour * 60 + ahora.minute
    # Historial: Carmen siempre con Carla (para «suele atenderse con»), otras al azar
    for dias in (35, 21, 7):
        agendar_en(carla, hoy - timedelta(days=dias), 10 * 60, Cita.Estado.ATENDIDA, quien=CLIENTES[0])
    for dias in range(1, 15, 2):
        for p in (carla, ana, luis):
            agendar_en(p, hoy - timedelta(days=dias), rnd.choice([9, 10, 11, 15, 16]) * 60,
                       Cita.Estado.NO_VINO if rnd.random() < .12 else Cita.Estado.ATENDIDA)
    # Hoy: lo de la mañana ya atendido; lo de la tarde, por confirmar o confirmado
    for p in (carla, ana, rosa, luis):
        for desde in (9 * 60, 10 * 60 + 30, 12 * 60, 15 * 60, 16 * 60 + 30, 18 * 60):
            if rnd.random() < .3:
                continue
            pasada = desde + 45 < min_ahora
            estado = Cita.Estado.ATENDIDA if pasada else rnd.choice([Cita.Estado.CONFIRMADA, Cita.Estado.CONFIRMADA, Cita.Estado.PENDIENTE])
            agendar_en(p, hoy, desde, estado)
    # Los últimos atendidos de hoy todavía no se cobran, y un cliente sin cita que avisó Luis
    for c in Cita.objects.filter(fecha=hoy, estado=Cita.Estado.ATENDIDA).order_by("-fin")[:2]:
        c.cobrada = False
        c.save(update_fields=["cobrada"])
    from .servicios import registrar_servicios

    barba = variantes.get("Corte + barba")
    if barba:
        registrar_servicios(cajero, luis, [barba[0]], "Martín Gómez", "979009900", "Pidió perfilado de cejas, ya incluido")
    # Próximos días
    for dias in range(1, 6):
        for p in (carla, ana, rosa, luis):
            for desde in (10 * 60, 15 * 60 + 30):
                if rnd.random() < .45:
                    agendar_en(p, hoy + timedelta(days=dias), desde, Cita.Estado.CONFIRMADA if dias == 1 else Cita.Estado.PENDIENTE)
    return Cita.objects.count()
