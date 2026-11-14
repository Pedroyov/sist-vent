from django.db import migrations


def crear(apps, schema_editor):
    """Rol Cocina y permiso mesas.cocina (para bases creadas antes de existir)."""
    from core.permisos import ADMINISTRACION, COCINA

    Group = apps.get_model("auth", "Group")
    PermisosRol = apps.get_model("core", "PermisosRol")
    g, _ = Group.objects.get_or_create(name=COCINA)
    pr, nuevo = PermisosRol.objects.get_or_create(grupo=g, defaults={
        "permisos": ["mesas.cocina"], "descripcion": "Ve los pedidos en la pantalla de cocina y los marca como listos."})
    if not nuevo and "mesas.cocina" not in (pr.permisos or []):
        pr.permisos = sorted(set(pr.permisos or []) | {"mesas.cocina"})
        pr.save(update_fields=["permisos"])


class Migration(migrations.Migration):
    dependencies = [("mesas", "0003_itemcuenta_listo_en_itemcuenta_servido_en"), ("core", "0002_roles_iniciales")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
