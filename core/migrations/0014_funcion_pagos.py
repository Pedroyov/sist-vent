from django.db import migrations


def apagar(apps, schema_editor):
    """«Pagos al personal» es una función nueva: en sistemas ya en uso empieza apagada."""
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        actuales = list(a.funciones_inactivas or [])
        if "pagos" not in actuales:
            a.funciones_inactivas = actuales + ["pagos"]
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0013_funciones_personal")]
    operations = [migrations.RunPython(apagar, migrations.RunPython.noop)]
