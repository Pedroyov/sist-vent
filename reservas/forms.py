from django import forms

from .models import Config, Reserva


class ReservaForm(forms.Form):
    fecha = forms.DateField(label="Día", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hora = forms.TimeField(label="Hora", widget=forms.TimeInput(attrs={"type": "time", "step": 300}, format="%H:%M"))
    personas = forms.IntegerField(label="Personas", min_value=1, max_value=200, initial=2,
                                  widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    telefono = forms.CharField(label="Celular", max_length=20, required=False,
                               widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "placeholder": "987654321", "autocomplete": "off"}))
    nombre = forms.CharField(label="Nombre", max_length=60, widget=forms.TextInput(attrs={"placeholder": "Ej.: Familia Pérez"}))
    mesas = forms.ModelMultipleChoiceField(label="Mesa", queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
                                           help_text="Opcional. Para un grupo grande marca varias: se juntan al llegar.")
    nota = forms.CharField(label="Nota", max_length=200, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ej.: cumpleaños, silla para bebé, terraza"}))
    permitir_choque = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, con_mesas=True, **kwargs):
        super().__init__(*args, **kwargs)
        if con_mesas:
            from mesas.models import Mesa

            self.fields["mesas"].queryset = Mesa.objects.filter(activa=True).select_related("zona")
        else:
            del self.fields["mesas"]

    @classmethod
    def desde(cls, r, **kw):
        return cls(initial={"fecha": r.fecha, "hora": r.hora, "personas": r.personas, "telefono": r.telefono, "nombre": r.nombre,
                            "mesas": [m.pk for m in r.mesas], "nota": r.nota}, **kw)


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["antes", "tolerancia", "duracion"]
