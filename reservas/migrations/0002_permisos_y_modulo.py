from django.db import migrations

NUEVOS = ["reservas.ver", "reservas.gestionar"]


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
        if "reservas" not in (a.modulos_inactivos or []):
            a.modulos_inactivos = list(a.modulos_inactivos or []) + ["reservas"]
            a.save(update_fields=["modulos_inactivos"])


class Migration(migrations.Migration):
    dependencies = [("reservas", "0001_initial"), ("core", "0012_funciones_avanzadas"), ("cobranzas", "0002_permisos_y_modulo")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
