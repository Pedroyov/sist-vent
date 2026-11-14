"""Datos iniciales: roles del sistema y niveles/grados de la educación básica regular (Perú)."""
from django.db import migrations

ROLES = ["Dirección", "Tesorería", "Docente"]

NIVELES = [
    ("Inicial", 1, ["3 años", "4 años", "5 años"]),
    ("Primaria", 2, ["1er grado", "2do grado", "3er grado", "4to grado", "5to grado", "6to grado"]),
    ("Secundaria", 3, ["1er año", "2do año", "3er año", "4to año", "5to año"]),
]


def crear(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Nivel = apps.get_model("core", "Nivel")
    Grado = apps.get_model("core", "Grado")

    for rol in ROLES:
        Group.objects.get_or_create(name=rol)

    for nombre, orden, grados in NIVELES:
        nivel, _ = Nivel.objects.get_or_create(nombre=nombre, defaults={"orden": orden})
        for i, g in enumerate(grados, start=1):
            Grado.objects.get_or_create(nivel=nivel, nombre=g, defaults={"orden": i})


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_inicial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
