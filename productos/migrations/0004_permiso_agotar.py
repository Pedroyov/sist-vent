from django.db import migrations

NUEVOS = ["productos.agotar"]


def agregar(apps, schema_editor):
    from core.permisos import PERMISOS, ROLES_BASE

    PermisosRol = apps.get_model("core", "PermisosRol")
    for pr in PermisosRol.objects.select_related("grupo").filter(grupo__name__in=ROLES_BASE):
        actuales = set(pr.permisos or [])
        nuevos = {c for c, _, _, roles in PERMISOS if c in NUEVOS and pr.grupo.name in roles}
        if not nuevos <= actuales:
            pr.permisos = sorted(actuales | nuevos)
            pr.save(update_fields=["permisos"])


class Migration(migrations.Migration):
    dependencies = [("productos", "0003_grupoopciones_producto_agotado_en_producto_grupos_and_more"), ("mesas", "0004_rol_cocina"), ("core", "0002_roles_iniciales")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
