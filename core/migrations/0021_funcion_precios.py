from django.db import migrations


def apagar(apps, schema_editor):
    """«Listas de precios» es una función nueva: en sistemas ya en uso empieza apagada."""
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        actuales = list(a.funciones_inactivas or [])
        if "precios" not in actuales:
            a.funciones_inactivas = actuales + ["precios"]
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0020_plazo_fiado")]
    operations = [migrations.RunPython(apagar, migrations.RunPython.noop)]
