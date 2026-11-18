"""Quien atiende pasa a ser una Persona del Personal (app `personal`, base del sistema).

Copia cada Profesional a Persona con el mismo id (así las citas, horarios y ausencias siguen apuntando bien), cambia las
relaciones y borra la tabla vieja. Si el negocio ya pagaba comisiones, la función «Comisiones» queda encendida.
"""
from django.db import migrations, models
import django.db.models.deletion


def copiar(apps, schema_editor):
    Profesional = apps.get_model("citas", "Profesional")
    Persona = apps.get_model("personal", "Persona")
    for p in Profesional.objects.all():
        nueva = Persona.objects.create(pk=p.pk, nombre=p.nombre, telefono=p.telefono, usuario_id=p.usuario_id, color=p.color,
                                       comision=p.comision, orden=p.orden, activo=p.activo, atiende_citas=True)
        nueva.servicios.set(p.servicios.all())
    Config = apps.get_model("citas", "Config")
    Ajustes = apps.get_model("core", "Ajustes")
    if Config.objects.filter(comisiones=True).exists():
        for a in Ajustes.objects.all():
            a.funciones_inactivas = [f for f in (a.funciones_inactivas or []) if f != "comisiones"]
            a.save(update_fields=["funciones_inactivas"])


class Migration(migrations.Migration):
    dependencies = [("citas", "0004_comisiones_y_precio"), ("personal", "0001_initial"), ("core", "0013_funciones_personal")]
    operations = [
        migrations.RunPython(copiar, migrations.RunPython.noop),
        migrations.AlterField("horario", "profesional",
                              models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="horarios", to="personal.persona")),
        migrations.AlterField("ausencia", "profesional",
                              models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ausencias", to="personal.persona")),
        migrations.AlterField("cita", "profesional",
                              models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="citas", to="personal.persona")),
        migrations.RemoveField("config", "comisiones"),
        migrations.DeleteModel("Profesional"),
    ]
