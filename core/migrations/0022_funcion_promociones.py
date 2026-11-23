from django.db import migrations


def apagar(apps, schema_editor):
    """«Promociones» es una función nueva: en sistemas ya en uso empieza apagada."""
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        actuales = list(a.funciones_inactivas or [])
        if "promociones" not in actuales:
            a.funciones_inactivas = actuales + ["promociones"]
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0021_funcion_precios")]
    operations = [migrations.RunPython(apagar, migrations.RunPython.noop)]
