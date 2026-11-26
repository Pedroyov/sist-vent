from django.db import migrations


def ajustar(apps, schema_editor):
    """«Menú del día» pasa a ser una función que se puede apagar. Queda encendida en restaurantes y donde ya se usa."""
    Ajustes = apps.get_model("core", "Ajustes")
    GrupoOpciones = apps.get_model("productos", "GrupoOpciones")
    en_uso = GrupoOpciones.objects.filter(diario=True).exists()
    for a in Ajustes.objects.all():
        actuales = list(a.funciones_inactivas or [])
        if a.rubro != "RES" and not en_uso and "menu" not in actuales:
            a.funciones_inactivas = actuales + ["menu"]
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0026_tipos_de_ticketera"), ("productos", "0015_porciones_del_dia")]
    operations = [migrations.RunPython(ajustar, migrations.RunPython.noop)]
