from django.db import migrations

NUEVOS = ["ventas.vender", "ventas.ver", "ventas.precio", "ventas.anular"]


def agregar(apps, schema_editor):
    """Da a los roles base los permisos de ventas que les tocan por defecto (sin quitar nada)."""
    from core.permisos import PERMISOS, ROLES_BASE

    PermisosRol = apps.get_model("core", "PermisosRol")
    for pr in PermisosRol.objects.select_related("grupo").filter(grupo__name__in=ROLES_BASE):
        actuales = set(pr.permisos or [])
        nuevos = {c for c, _, _, roles in PERMISOS if c in NUEVOS and pr.grupo.name in roles}
        if not nuevos <= actuales:
            pr.permisos = sorted(actuales | nuevos)
            pr.save(update_fields=["permisos"])


class Migration(migrations.Migration):
    dependencies = [("ventas", "0001_initial"), ("core", "0002_roles_iniciales")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
