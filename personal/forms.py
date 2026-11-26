from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from .models import Persona


class PersonaForm(forms.ModelForm):
    """Cada módulo muestra solo sus campos: sin Citas no se ven los servicios; sin Delivery, «reparte»; sin comisiones, el %."""

    class Meta:
        model = Persona
        fields = ["nombre", "telefono", "usuario", "color", "comision", "sueldo", "sueldo_cada", "atiende_citas", "reparte", "servicios",
                  "orden", "activo"]
        widgets = {"sueldo": forms.NumberInput(attrs={"step": "0.10", "min": "0", "inputmode": "decimal"}), "servicios": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}), "color": forms.RadioSelect,
                   "telefono": forms.TextInput(attrs={"type": "tel", "inputmode": "tel"})}

    def __init__(self, *args, modulos=(), comisiones=False, pagos=False, **kwargs):
        super().__init__(*args, **kwargs)
        from productos.models import Producto

        usados = Persona.objects.exclude(pk=self.instance.pk).exclude(usuario=None).values_list("usuario_id", flat=True)
        User = get_user_model()
        self.fields["usuario"].queryset = User.objects.filter(is_active=True).exclude(pk__in=usados).order_by("first_name", "username")
        self.fields["usuario"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.username})"
        self.fields["usuario"].empty_label = "Sin usuario (no entra al sistema)"
        self.fields["orden"].label = "Orden en las listas"
        self.fields["orden"].help_text = ("En qué lugar sale esta persona en la agenda de citas, en «¿Quién atendió?» y en los pagos: "
                                          "el número menor sale primero. Con todos en 0 se ordenan por nombre.")
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
        if not pagos:
            del self.fields["sueldo"]
            del self.fields["sueldo_cada"]
        else:
            self.fields["sueldo"].required = self.fields["sueldo_cada"].required = False

    def clean_sueldo(self):
        return self.cleaned_data.get("sueldo") or Decimal("0")

    def clean_sueldo_cada(self):
        return self.cleaned_data.get("sueldo_cada") or "MES"
