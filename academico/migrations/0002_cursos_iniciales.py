"""Áreas curriculares del Currículo Nacional (EBR) por nivel. Se pueden editar después."""
from django.db import migrations

CURSOS = {
    "Inicial": [
        ("Personal Social", "PS"), ("Psicomotriz", "PSI"), ("Comunicación", "COM"),
        ("Matemática", "MAT"), ("Ciencia y Tecnología", "CYT"),
    ],
    "Primaria": [
        ("Matemática", "MAT"), ("Comunicación", "COM"), ("Inglés", "ING"), ("Personal Social", "PS"),
        ("Arte y Cultura", "AYC"), ("Ciencia y Tecnología", "CYT"), ("Educación Física", "EF"),
        ("Educación Religiosa", "ER"),
    ],
    "Secundaria": [
        ("Matemática", "MAT"), ("Comunicación", "COM"), ("Inglés", "ING"), ("Arte y Cultura", "AYC"),
        ("Ciencias Sociales", "CCSS"), ("Desarrollo Personal, Ciudadanía y Cívica", "DPCC"),
        ("Educación Física", "EF"), ("Educación Religiosa", "ER"), ("Ciencia y Tecnología", "CYT"),
        ("Educación para el Trabajo", "EPT"),
    ],
}


def crear(apps, schema_editor):
    Nivel = apps.get_model("core", "Nivel")
    Curso = apps.get_model("academico", "Curso")
    for nivel in Nivel.objects.all():
        for i, (nombre, abrev) in enumerate(CURSOS.get(nivel.nombre, []), start=1):
            Curso.objects.get_or_create(nivel=nivel, nombre=nombre, defaults={"abreviatura": abrev, "orden": i})


class Migration(migrations.Migration):
    dependencies = [("academico", "0001_initial"), ("core", "0002_datos_iniciales")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
