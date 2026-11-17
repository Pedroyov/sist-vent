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
    mesa = forms.ModelChoiceField(label="Mesa", queryset=None, required=False, empty_label="Sin mesa (se elige al llegar)")
    nota = forms.CharField(label="Nota", max_length=200, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ej.: cumpleaños, silla para bebé, terraza"}))
    permitir_choque = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, con_mesas=True, **kwargs):
        super().__init__(*args, **kwargs)
        if con_mesas:
            from mesas.models import Mesa

            self.fields["mesa"].queryset = Mesa.objects.filter(activa=True).select_related("zona")
            self.fields["mesa"].label_from_instance = lambda m: f"Mesa {m.nombre} · {m.zona.nombre} · {m.capacidad} pers."
        else:
            del self.fields["mesa"]

    @classmethod
    def desde(cls, r, **kw):
        return cls(initial={"fecha": r.fecha, "hora": r.hora, "personas": r.personas, "telefono": r.telefono, "nombre": r.nombre,
                            "mesa": r.mesa_id, "nota": r.nota}, **kw)


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["antes", "tolerancia", "duracion"]
