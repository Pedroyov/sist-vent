from django.db import migrations


def crear(apps, schema_editor):
    """Rol Mozo: toma pedidos y entrega la precuenta; el cliente paga en caja. No cobra ni abre caja."""
    from core.permisos import MOZO, permisos_por_defecto

    Group = apps.get_model("auth", "Group")
    PermisosRol = apps.get_model("core", "PermisosRol")
    g, _ = Group.objects.get_or_create(name=MOZO)
    PermisosRol.objects.get_or_create(grupo=g, defaults={
        "permisos": permisos_por_defecto(MOZO),
        "descripcion": "Atiende las mesas desde su celular: toma pedidos, envía a cocina y entrega la precuenta. El cobro se hace en caja."})


class Migration(migrations.Migration):
    dependencies = [("mesas", "0007_delivery"), ("core", "0008_modulos_cocina_delivery")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
