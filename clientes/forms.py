from django import forms

from .documentos import validar
from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["tipo_documento", "numero_documento", "nombre", "telefono", "email", "direccion", "limite_credito", "nota", "activo"]
        widgets = {
            "numero_documento": forms.TextInput(attrs={"inputmode": "numeric", "autofocus": True}),
            "telefono": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "987654321"}),
            "limite_credito": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
        }

    def __init__(self, *args, puede_limite=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero_documento"].required = False
        if not puede_limite:
            self.fields["limite_credito"].disabled = True
            self.fields["limite_credito"].help_text = "Solo lo cambia quien tiene permiso especial de fiado."

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo_documento")
        numero, error = validar(tipo, datos.get("numero_documento"))
        if error:
            self.add_error("numero_documento", error)
        else:
            datos["numero_documento"] = numero
            otro = Cliente.objects.filter(tipo_documento=tipo, numero_documento=numero).exclude(pk=self.instance.pk).first() if numero else None
            if otro:
                self.add_error("numero_documento", f"Ya está registrado: {otro.nombre}.")
        if datos.get("nombre"):
            datos["nombre"] = " ".join(datos["nombre"].split())
        return datos


class AbonoForm(forms.Form):
    monto = forms.DecimalField(label="Monto que paga", min_value=0.01, decimal_places=2,
                               widget=forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal", "class": "form-control-lg"}))
    metodo = forms.ChoiceField(label="Cómo paga")
    nota = forms.CharField(label="Nota", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ventas.models import MetodoPago

        self.fields["metodo"].choices = [(k, v) for k, v in MetodoPago.choices if k != MetodoPago.CREDITO]
