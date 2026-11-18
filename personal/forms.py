from django import forms
from django.contrib.auth import get_user_model

from .models import Persona


class PersonaForm(forms.ModelForm):
    """Cada módulo muestra solo sus campos: sin Citas no se ven los servicios; sin Delivery, «reparte»; sin comisiones, el %."""

    class Meta:
        model = Persona
        fields = ["nombre", "telefono", "usuario", "color", "comision", "atiende_citas", "reparte", "servicios", "orden", "activo"]
        widgets = {"servicios": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}), "color": forms.RadioSelect,
                   "telefono": forms.TextInput(attrs={"type": "tel", "inputmode": "tel"})}

    def __init__(self, *args, modulos=(), comisiones=False, **kwargs):
        super().__init__(*args, **kwargs)
        from productos.models import Producto

        usados = Persona.objects.exclude(pk=self.instance.pk).exclude(usuario=None).values_list("usuario_id", flat=True)
        User = get_user_model()
        self.fields["usuario"].queryset = User.objects.filter(is_active=True).exclude(pk__in=usados).order_by("first_name", "username")
        self.fields["usuario"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.username})"
        self.fields["usuario"].empty_label = "Sin usuario (no entra al sistema)"
        if "citas" in modulos:
            self.fields["servicios"].queryset = Producto.objects.filter(tipo=Producto.Tipo.SERVICIO, activo=True).order_by("nombre")
            self.fields["servicios"].label = "Servicios que hace"
        else:
            del self.fields["servicios"]
            del self.fields["atiende_citas"]
        if "delivery" not in modulos:
            del self.fields["reparte"]
        if not comisiones:
            del self.fields["comision"]
