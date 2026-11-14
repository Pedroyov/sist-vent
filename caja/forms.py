from decimal import Decimal

from django import forms

from .models import MovimientoCaja

DINERO = {"step": "0.10", "min": "0", "inputmode": "decimal"}


class AbrirForm(forms.Form):
    monto_inicial = forms.DecimalField(label="Efectivo con el que empiezas (sencillo)", min_value=Decimal("0"), decimal_places=2,
                                       widget=forms.NumberInput(attrs={**DINERO, "autofocus": True, "class": "form-control-lg"}))
    nota = forms.CharField(label="Nota", max_length=200, required=False)


class MovimientoForm(forms.ModelForm):
    class Meta:
        model = MovimientoCaja
        fields = ["categoria", "monto", "concepto"]
        widgets = {"monto": forms.NumberInput(attrs={**DINERO, "autofocus": True})}

    def __init__(self, *args, tipo=MovimientoCaja.Tipo.EGRESO, **kwargs):
        super().__init__(*args, **kwargs)
        C = MovimientoCaja.Categoria
        if tipo == MovimientoCaja.Tipo.INGRESO:
            opciones = [C.SENCILLO, C.OTRO]
        else:
            opciones = [C.PROVEEDOR, C.GASTO, C.PERSONAL, C.RETIRO, C.DEVOLUCION, C.OTRO]
        self.fields["categoria"].choices = [(c.value, c.label) for c in opciones]


class CerrarForm(forms.Form):
    contado = forms.DecimalField(label="Efectivo contado en el cajón", min_value=Decimal("0"), decimal_places=2,
                                 widget=forms.NumberInput(attrs={**DINERO, "class": "form-control-lg text-end"}))
    nota = forms.CharField(label="Nota del cierre", max_length=300, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ej.: faltan S/ 2, se dio mal un vuelto"}))
