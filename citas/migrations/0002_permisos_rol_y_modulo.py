from django.db import migrations

NUEVOS = ["citas.ver", "citas.gestionar", "citas.personal", "citas.mi_agenda", "citas.agendar_propias"]


def agregar(apps, schema_editor):
    """Rol «Profesional», permisos por defecto de los roles base y, en sistemas ya en uso, el módulo empieza apagado."""
    from core.permisos import PERMISOS, PROFESIONAL, ROLES_BASE, permisos_por_defecto

    Group = apps.get_model("auth", "Group")
    PermisosRol = apps.get_model("core", "PermisosRol")
    g, _ = Group.objects.get_or_create(name=PROFESIONAL)
    PermisosRol.objects.get_or_create(grupo=g, defaults={
        "permisos": permisos_por_defecto(PROFESIONAL),
        "descripcion": "Quien atiende (estilista, barbero, terapeuta): ve su agenda en el celular y comparte sus horarios libres."})
    for pr in PermisosRol.objects.select_related("grupo").filter(grupo__name__in=ROLES_BASE):
        actuales = set(pr.permisos or [])
        nuevos = {c for c, _, _, roles in PERMISOS if c in NUEVOS and pr.grupo.name in roles}
        if not nuevos <= actuales:
            pr.permisos = sorted(actuales | nuevos)
            pr.save(update_fields=["permisos"])
    Ajustes = apps.get_model("core", "Ajustes")
    for a in Ajustes.objects.all():
        if "citas" not in (a.modulos_inactivos or []):
            a.modulos_inactivos = list(a.modulos_inactivos or []) + ["citas"]
            a.save(update_fields=["modulos_inactivos"])


class Migration(migrations.Migration):
    dependencies = [("citas", "0001_initial"), ("reservas", "0002_permisos_y_modulo")]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
