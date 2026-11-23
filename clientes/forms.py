from django import forms

from .documentos import validar
from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["tipo_documento", "numero_documento", "nombre", "telefono", "email", "direccion", "limite_credito", "dias_credito", "lista", "nota", "activo"]
        widgets = {
            "numero_documento": forms.TextInput(attrs={"inputmode": "numeric", "autofocus": True}),
            "telefono": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "987654321"}),
            "limite_credito": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "decimal"}),
            "dias_credito": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "numeric"}),
        }

    def __init__(self, *args, puede_limite=True, puede_precio=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero_documento"].required = False
        from productos.models import ListaPrecios
        from productos.precios import activa

        if not activa():
            del self.fields["lista"]
        else:
            self.fields["lista"].queryset = ListaPrecios.objects.filter(activa=True) | ListaPrecios.objects.filter(pk=self.instance.lista_id or 0)
            self.fields["lista"].empty_label = "Precio normal"
            if not puede_precio:
                self.fields["lista"].disabled = True
                self.fields["lista"].help_text = "Solo la cambia quien puede cambiar precios."
        if not puede_limite:
            self.fields["limite_credito"].disabled = True
            self.fields["limite_credito"].help_text = "Solo lo cambia quien tiene permiso especial de fiado."
            self.fields["dias_credito"].disabled = True
            self.fields["dias_credito"].help_text = "Solo lo cambia quien tiene permiso especial de fiado."
        else:
            from core.models import Ajustes

            general = Ajustes.cargar().dias_fiado
            self.fields["dias_credito"].widget.attrs["placeholder"] = f"{general} (el general)" if general else "Sin plazo (el general)"

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
    referencia = forms.CharField(label="N° de operación", max_length=60, required=False,
                                 help_text="De Yape, Plin, tarjeta o transferencia. Ayuda a conciliar con el banco.")
    nota = forms.CharField(label="Nota", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ventas.models import MetodoPago

        self.fields["metodo"].choices = [(k, v) for k, v in MetodoPago.choices if k not in (MetodoPago.CREDITO, MetodoPago.SALDO)]
