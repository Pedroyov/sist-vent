"""Planes, inscritos, cuotas y pagos de ejemplo (python manage.py datos_demo --rubro ACA)."""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from clientes.models import Cliente

from .models import Config, Cuota, Pago, Plan
from .servicios import cobrar, inscribir, sumar_meses

PLANES = [
    # nombre, precio, frecuencia, cuotas, matrícula, descripción
    ("Gimnasio mensual", "90", "MEN", 0, "0", "Lunes a sábado, 6 a. m. a 10 p. m."),
    ("Natación niños", "120", "MEN", 0, "30", "Martes y jueves, 4 p. m."),
    ("Inglés básico (6 meses)", "150", "MEN", 6, "50", "Sábados, 9 a. m."),
    ("Taller de vacaciones", "250", "UNI", 0, "0", "Enero y febrero"),
]

PERSONAS = [
    # cliente, DNI, celular, alumno (vacío = el mismo), plan, meses desde que empezó, cuántas cuotas debe
    ("Carmen Salazar Ruiz", "41526374", "987120301", "", 0, 5, 0),
    ("Jorge Villanueva Paz", "42637485", "987120302", "", 0, 3, 1),
    ("Lucía Fernández Gil", "43748596", "987120303", "", 0, 2, 0),
    ("Miguel Ángel Ccori", "44859607", "987120304", "", 0, 1, 0),
    ("Patricia Núñez Vega", "45960718", "987120305", "", 0, 4, 2),
    ("Raúl Espinoza Lazo", "46071829", "", "", 0, 0, 0),
    ("Rosa Mamani Cruz", "72345611", "985555666", "Valentina Mamani", 1, 3, 0),
    ("Rosa Mamani Cruz", "72345611", "985555666", "Thiago Mamani", 1, 3, 1),
    ("Diego Paredes Soto", "47182930", "987120307", "Camila Paredes", 1, 2, 0),
    ("Elena Quispe Tito", "48293041", "987120308", "Sebastián Quispe", 1, 1, 1),
    ("Andrés Rojas Mejía", "49304152", "987120309", "", 2, 4, 0),
    ("Sofía Huamán León", "40415263", "987120310", "", 2, 3, 2),
    ("Martín Castro Ibáñez", "41526399", "987120311", "Daniela Castro", 2, 2, 0),
    ("Gabriela Ortiz Ramos", "42637400", "987120312", "", 2, 0, 0),
    ("Fernando Díaz Chávez", "43748511", "987120313", "Lucas Díaz", 3, 1, 0),
]


def cargar_cobranzas():
    if Plan.objects.exists():
        return Plan.objects.count()
    azar = random.Random(7)
    User = get_user_model()
    cajero = User.objects.filter(username="cajero").first() or User.objects.filter(is_superuser=True).first()
    cfg = Config.cargar()
    cfg.dias_aviso = 5
    cfg.save()
    planes = [Plan.objects.create(nombre=n, precio=Decimal(p), frecuencia=f, num_cuotas=c, matricula=Decimal(m), descripcion=d, orden=i * 10)
              for i, (n, p, f, c, m, d) in enumerate(PLANES)]
    hoy = timezone.localdate()
    metodos = ["EFE", "EFE", "YAP", "YAP", "PLI", "TAR", "TRA"]
    for nombre, dni, cel, alumno, plan_i, meses, debe in PERSONAS:
        cliente, _ = Cliente.objects.get_or_create(tipo_documento="DNI", numero_documento=dni, defaults={"nombre": nombre, "telefono": cel})
        plan = planes[plan_i]
        inicio = sumar_meses(hoy, -meses, hoy.day) - timedelta(days=azar.randint(0, 12)) if meses else hoy - timedelta(days=azar.randint(0, 3))
        if dni in ("43748596", "49304152"):  # a estos les vence en dos días (para ver «Vencen pronto»)
            inicio = sumar_meses(hoy, -meses, hoy.day) + timedelta(days=2)
        dia = 5 if plan.num_cuotas else None  # el curso cobra los días 5
        insc = inscribir(cliente, plan, cajero, inicio=inicio, dia_pago=dia, alumno=alumno)
        vencidas = list(insc.cuotas.filter(vence__lte=hoy).order_by("vence", "numero"))
        a_pagar = vencidas[:max(0, len(vencidas) - debe)]
        for c in a_pagar:
            p = cobrar(cliente, [c.pk], c.total, azar.choice(metodos), cajero)
            cuando = timezone.make_aware(datetime.combine(c.vence + timedelta(days=azar.randint(0, 3)), time.min)) + timedelta(hours=azar.randint(8, 20), minutes=azar.randint(0, 59))
            if cuando.date() < hoy:  # los pagos de días pasados no van a la caja de hoy
                Pago.objects.filter(pk=p.pk).update(fecha=cuando, sesion_caja=None)
        if debe == 1 and plan.precio > 100 and len(vencidas) > len(a_pagar):  # uno pagó una parte
            c = vencidas[len(a_pagar)]
            cobrar(cliente, [c.pk], Decimal("50"), "YAP", cajero, nota="A cuenta")
    return Plan.objects.count()
