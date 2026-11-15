from django.db import migrations

NUEVOS = ["facturacion.ver", "facturacion.configurar"]


def agregar(apps, schema_editor):
    """Permisos por defecto para los roles base y, en sistemas que ya estaban en uso, el módulo empieza apagado."""
    from core.permisos import PERMISOS, ROLES_BASE

    PermisosRol = apps.get_model("core", "PermisosRol")
    for pr in PermisosRol.objects.select_related("grupo").filter(grupo__name__in=ROLES_BASE):
        actuales = set(pr.permisos or [])
        nuevos = {c for c, _, _, roles in PERMISOS if c in NUEVOS and pr.grupo.name in roles}
        if not nuevos <= actuales:
            pr.permisos = sorted(actuales | nuevos)
            pr.save(update_fields=["permisos"])
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        if "facturacion" not in (a.modulos_inactivos or []):
            a.modulos_inactivos = list(a.modulos_inactivos or []) + ["facturacion"]
            a.save(update_fields=["modulos_inactivos"])


class Migration(migrations.Migration):
    dependencies = [("facturacion", "0001_initial"), ("core", "0008_modulos_cocina_delivery"), ("mesas", "0008_rol_mozo")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
