"""Personal de ejemplo (python manage.py datos_demo). En peluquería lo crea citas/demo.py con sus horarios."""
from django.contrib.auth import get_user_model

from core.models import Rubro

from .models import Persona


def cargar_personal(rubro):
    User = get_user_model()
    u = {x.username: x for x in User.objects.filter(username__in=["vendedor", "mozo", "cajero"])}
    if rubro == Rubro.RESTAURANTE:
        for i, (nombre, usuario, color) in enumerate((("Ana", "vendedor", "#d63384"), ("Jorge", "mozo", "#0d6efd"))):
            if usuario in u:
                Persona.objects.get_or_create(usuario=u[usuario], defaults={"nombre": nombre, "color": color, "orden": i, "atiende_citas": False})
        for nombre, color in (("Carlos (moto)", "#fd7e14"), ("Jhon (bici)", "#198754")):
            Persona.objects.get_or_create(nombre=nombre, defaults={"color": color, "reparte": True, "atiende_citas": False, "orden": 9})
    elif rubro in (Rubro.TIENDA, Rubro.ROPA, Rubro.LIBRERIA) and "vendedor" in u:
        Persona.objects.get_or_create(usuario=u["vendedor"], defaults={"nombre": "Ana", "color": "#d63384", "atiende_citas": False})
        if rubro == Rubro.TIENDA:
            Persona.objects.get_or_create(nombre="Beto (moto)", defaults={"color": "#fd7e14", "reparte": True, "atiende_citas": False})
    return Persona.objects.count()
