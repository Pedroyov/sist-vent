from django.db import migrations

DESCRIPCIONES = {
    "Administración": "Acceso total (no se puede limitar).",
    "Cajero": "Cobra las ventas y maneja la caja.",
    "Vendedor": "Registra pedidos y ventas.",
}


def roles_iniciales(apps, schema_editor):
    from core.permisos import ROLES_BASE, permisos_por_defecto

    Group = apps.get_model("auth", "Group")
    PermisosRol = apps.get_model("core", "PermisosRol")
    for rol in ROLES_BASE:
        g, _ = Group.objects.get_or_create(name=rol)
        PermisosRol.objects.update_or_create(grupo=g, defaults={
            "permisos": permisos_por_defecto(rol), "descripcion": DESCRIPCIONES.get(rol, "")})


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(roles_iniciales, migrations.RunPython.noop)]
