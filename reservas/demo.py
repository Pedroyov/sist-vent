"""Reservas de ejemplo para el restaurante (las usa python manage.py datos_demo --rubro RES).

Las horas se calculan desde «ahora», para que la demo siempre muestre algo: una mesa reservada en el mapa, una reserva
atrasada, reservas por confirmar y las de los próximos días.
"""
import random
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Reserva

NOMBRES = [("Familia Pérez", "987123456"), ("Carla Mendoza", "986234567"), ("Jorge Salazar", "985345678"), ("Cumpleaños Ana", "984456789"),
           ("Luis Torres", "983567890"), ("Familia Rojas", "982678901"), ("María Chávez", "981789012"), ("Empresa Andina", "980890123"),
           ("Patricia León", "979901234"), ("Diego Vargas", "978012345"), ("Rosa Quintana", "977123450"), ("Grupo de amigos", "976234561")]
NOTAS = ["", "", "", "Cumpleaños: traen torta", "Silla para bebé", "Cerca de la ventana", "Terraza si se puede", ""]


def _redondo(dt, minutos=15):
    dt = dt.replace(second=0, microsecond=0)
    return dt + timedelta(minutes=(minutos - dt.minute % minutos) % minutos)


def cargar_reservas():
    from mesas.models import Cuenta, Mesa

    rnd = random.Random(7)
    User = get_user_model()
    cajero = User.objects.filter(username="cajero").first() or User.objects.filter(is_superuser=True).first()
    ocupadas = set(Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA, mesa__isnull=False).values_list("mesa_id", flat=True))
    libres = [m for m in Mesa.objects.filter(activa=True) if m.pk not in ocupadas]
    todas = list(Mesa.objects.filter(activa=True))
    ahora = timezone.localtime()
    hoy = ahora.date()
    gente = list(NOMBRES)
    rnd.shuffle(gente)

    def nueva(momento, estado, mesa=None, personas=None, creada=None):
        nombre, tel = gente.pop() if gente else ("Cliente", "")
        return Reserva.objects.create(fecha=momento.date(), hora=momento.time(), personas=personas or rnd.choice([2, 2, 3, 4, 4, 5, 6, 8]),
                                      nombre=nombre, telefono=tel, mesa=mesa, nota=rnd.choice(NOTAS), estado=estado, creada_por=cajero,
                                      creada_en=creada or (momento - timedelta(days=rnd.randint(1, 4))))

    # Hoy: una que ya llegó, una que no vino, una atrasada, una que se ve en el mapa y las de la noche
    for horas, estado in ((-4, Reserva.Estado.LLEGO), (-3, Reserva.Estado.NO_VINO), (-0.75, Reserva.Estado.CONFIRMADA)):
        m = _redondo(ahora + timedelta(hours=horas))
        if m.date() == hoy:
            nueva(m, estado, mesa=rnd.choice(todas) if estado == Reserva.Estado.LLEGO else None)
    if libres:
        m = _redondo(ahora + timedelta(minutes=40))
        if m.date() == hoy:
            nueva(m, Reserva.Estado.CONFIRMADA, mesa=libres.pop(0), personas=4)
    for horas, estado in ((2, Reserva.Estado.PENDIENTE), (3, Reserva.Estado.CONFIRMADA)):
        m = _redondo(ahora + timedelta(hours=horas), 30)
        if m.date() == hoy:
            nueva(m, estado, mesa=libres.pop(0) if libres else None)
    # Próximos días
    for dias, hora, estado, con_mesa in ((1, "13:00", Reserva.Estado.CONFIRMADA, True), (1, "20:00", Reserva.Estado.PENDIENTE, True),
                                         (1, "20:30", Reserva.Estado.PENDIENTE, False), (2, "21:00", Reserva.Estado.CONFIRMADA, True),
                                         (4, "13:30", Reserva.Estado.PENDIENTE, False), (5, "20:00", Reserva.Estado.CONFIRMADA, True)):
        f = timezone.make_aware(datetime.combine(hoy + timedelta(days=dias), datetime.strptime(hora, "%H:%M").time()))
        nueva(timezone.localtime(f), estado, mesa=rnd.choice(todas) if con_mesa else None, creada=ahora - timedelta(hours=rnd.randint(1, 30)))
    # Historial: días pasados (sirve para el aviso «no vino N veces»)
    for dias in range(2, 12, 2):
        f = timezone.make_aware(datetime.combine(hoy - timedelta(days=dias), datetime.strptime("20:00", "%H:%M").time()))
        gente.append(NOMBRES[dias % len(NOMBRES)])
        nueva(timezone.localtime(f), Reserva.Estado.LLEGO if dias % 3 else Reserva.Estado.NO_VINO, mesa=rnd.choice(todas))
    return Reserva.objects.count()
