from django import forms

from core.forms import FECHA

from .models import MENSAJE_RECORDATORIO, ConfigCobranza, Descuento, Pago


class ConfigCobranzaForm(forms.ModelForm):
    class Meta:
        model = ConfigCobranza
        fields = [
            "monto_matricula", "monto_pension", "mes_inicio", "mes_fin", "dia_vencimiento",
            "mora_activa", "mora_tipo", "mora_monto", "mora_dias_gracia", "mensaje_recordatorio",
        ]
        widgets = {
            "monto_matricula": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
            "monto_pension": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
            "mora_monto": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
            "mensaje_recordatorio": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mensaje_recordatorio"].required = False

    def clean_mensaje_recordatorio(self):
        # si se deja vacío, se usa el mensaje estándar
        return (self.cleaned_data.get("mensaje_recordatorio") or "").strip() or MENSAJE_RECORDATORIO

    def clean(self):
        datos = super().clean()
        if datos.get("mes_inicio") and datos.get("mes_fin") and datos["mes_fin"] < datos["mes_inicio"]:
            self.add_error("mes_fin", "Debe ser igual o posterior a la primera pensión.")
        if datos.get("mora_activa") and not datos.get("mora_monto"):
            self.add_error("mora_monto", "Indica el monto de la mora.")
        return datos


class DescuentoForm(forms.ModelForm):
    class Meta:
        model = Descuento
        fields = ["motivo", "tipo", "valor", "en_pensiones", "en_matricula"]
        widgets = {"valor": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"})}

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") == Descuento.Tipo.PORCENTAJE and datos.get("valor") and datos["valor"] > 100:
            self.add_error("valor", "El porcentaje no puede ser mayor que 100.")
        if not datos.get("en_pensiones") and not datos.get("en_matricula"):
            raise forms.ValidationError("Marca si aplica a pensiones, a matrícula o a ambas.")
        return datos


class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ["fecha", "metodo", "numero_operacion", "voucher", "observacion"]
        widgets = {
            "fecha": FECHA,
            "voucher": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def clean(self):
        datos = super().clean()
        metodo = datos.get("metodo")
        if metodo and metodo != Pago.Metodo.EFECTIVO and not datos.get("numero_operacion") and not datos.get("voucher"):
            self.add_error("numero_operacion", "Para pagos que no son en efectivo, anota el N° de operación o sube la foto del voucher.")
        return datos


class AnularPagoForm(forms.Form):
    motivo = forms.CharField(label="Motivo de la anulación", max_length=200)
