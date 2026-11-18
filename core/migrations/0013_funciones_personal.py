from django.db import migrations


def apagar(apps, schema_editor):
    """«Quién atendió» y «Comisiones» son funciones nuevas: en sistemas ya en uso empiezan apagadas."""
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        actuales = list(a.funciones_inactivas or [])
        nuevas = [f for f in ("atendio", "comisiones") if f not in actuales]
        if nuevas:
            a.funciones_inactivas = actuales + nuevas
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0012_funciones_avanzadas")]
    operations = [migrations.RunPython(apagar, migrations.RunPython.noop)]
