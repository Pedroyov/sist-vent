from django.db import migrations

EQUIVALENTE = {"mesas.atender": "delivery.atender", "mesas.cobrar": "delivery.cobrar", "mesas.anular": "delivery.anular"}


def agregar(apps, schema_editor):
    """El delivery ya no depende de Mesas y tiene sus propios permisos: quien atendía, cobraba o anulaba mesas (y por eso
    también los delivery) los recibe; los roles base, los que les tocan por defecto."""
    from core.permisos import PERMISOS, ROLES_BASE

    PermisosRol = apps.get_model("core", "PermisosRol")
    for pr in PermisosRol.objects.select_related("grupo"):
        actuales = set(pr.permisos or [])
        nuevos = {d for m, d in EQUIVALENTE.items() if m in actuales}
        if pr.grupo.name in ROLES_BASE:
            nuevos |= {c for c, mod, _, roles in PERMISOS if mod == "delivery" and pr.grupo.name in roles}
        if not nuevos <= actuales:
            pr.permisos = sorted(actuales | nuevos)
            pr.save(update_fields=["permisos"])


class Migration(migrations.Migration):
    dependencies = [("core", "0010_rubro_academia")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
