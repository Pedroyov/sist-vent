from django.db import migrations


def apagar(apps, schema_editor):
    """Compras es un módulo nuevo: en sistemas ya en uso empieza apagado (se enciende en Configuración → Módulos)."""
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        if "compras" not in (a.modulos_inactivos or []):
            a.modulos_inactivos = list(a.modulos_inactivos or []) + ["compras"]
            a.save(update_fields=["modulos_inactivos"])


class Migration(migrations.Migration):
    dependencies = [("compras", "0001_initial"), ("core", "0014_funcion_pagos")]
    operations = [migrations.RunPython(apagar, migrations.RunPython.noop)]
