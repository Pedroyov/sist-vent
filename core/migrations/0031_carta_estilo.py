import core.utils
from django.db import migrations, models


class Migration(migrations.Migration):
    """Estilo y foto de portada de la carta digital (aparte de 0030, que ya estaba aplicada en algunas bases)."""

    dependencies = [
        ('core', '0030_carta_digital'),
    ]

    operations = [
        migrations.AddField(
            model_name='ajustes',
            name='carta_estilo',
            field=models.CharField(choices=[('CLA', 'Clara (fondo crema)'), ('OSC', 'Oscura (fondo negro, títulos dorados)')], default='CLA', max_length=3, verbose_name='estilo de la carta'),
        ),
        migrations.AddField(
            model_name='ajustes',
            name='carta_portada',
            field=models.ImageField(blank=True, help_text='Opcional: el local o sus platos. Sale arriba, de fondo del nombre. Los platos no llevan foto.', upload_to='negocio/', validators=[core.utils.TamanoMaximo(5)], verbose_name='foto de portada de la carta'),
        ),
    ]
