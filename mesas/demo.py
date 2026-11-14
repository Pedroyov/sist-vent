"""Mesas de ejemplo para el rubro restaurante (las usa python manage.py datos_demo)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from productos.models import Variante

from .models import Cuenta, Mesa, Zona
from .servicios import abrir_cuenta, agregar, enviar_cocina


def cargar_mesas():
    if Mesa.objects.exists():
        return Mesa.objects.count()
    salon, _ = Zona.objects.get_or_create(nombre="Salón", defaults={"orden": 10})
    terraza, _ = Zona.objects.get_or_create(nombre="Terraza", defaults={"orden": 20})
    for n in range(1, 9):
        Mesa.objects.create(zona=salon, nombre=str(n), capacidad=6 if n in (4, 8) else 4, orden=n)
    for n in range(1, 5):
        Mesa.objects.create(zona=terraza, nombre=f"T{n}", capacidad=2, orden=n)

    User = get_user_model()
    mozo = User.objects.filter(username="vendedor").first() or User.objects.first()
    variantes = {v.nombre_completo: v for v in Variante.objects.filter(activa=True).select_related("producto")}

    def pedir(cuenta, pedidos, enviar=True, minutos=0):
        items = [{"variante": variantes[n].pk, "cantidad": c, "nota": nota} for n, c, nota in pedidos if n in variantes]
        if items:
            agregar(cuenta, items, mozo)
            if enviar:
                enviar_cocina(cuenta)
        Cuenta.objects.filter(pk=cuenta.pk).update(abierta_en=timezone.now() - timedelta(minutes=minutos))

    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="2"), 3)
    pedir(c, [("Pollo a la brasa · 1/2", 1, ""), ("Chicha morada · Jarra 1 L", 1, ""), ("Papa a la huancaína", 1, "sin aceituna")], minutos=35)
    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="5"), 2)
    pedir(c, [("Lomo saltado", 2, "uno sin cebolla"), ("Inca Kola 500 ml", 2, "")], minutos=52)
    Cuenta.objects.filter(pk=c.pk).update(pidio_cuenta=True)
    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="T1"), 2)
    pedir(c, [("Menú ejecutivo", 2, "")], enviar=False, minutos=4)
    return Mesa.objects.count()
