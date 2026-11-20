import re
from decimal import Decimal

from django import forms

from .models import Compra, Proveedor

DINERO = {"step": "0.10", "min": "0", "inputmode": "decimal"}


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ["ruc", "nombre", "comercial", "contacto", "telefono", "email", "direccion", "plazo", "nota", "activo"]
        widgets = {"ruc": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 11}),
                   "telefono": forms.TextInput(attrs={"type": "tel", "inputmode": "tel"})}

    def clean_ruc(self):
        from clientes.documentos import ruc_valido

        ruc = re.sub(r"\D", "", self.cleaned_data.get("ruc") or "")
        if ruc and not (len(ruc) == 8 or ruc_valido(ruc)):
            raise forms.ValidationError("Escribe un RUC válido (11 dígitos) o un DNI (8 dígitos).")
        if ruc and Proveedor.objects.exclude(pk=self.instance.pk).filter(ruc=ruc).exists():
            raise forms.ValidationError("Ya hay un proveedor con ese RUC.")
        return ruc

    def clean_nombre(self):
        return " ".join(self.cleaned_data["nombre"].split())


class CompraForm(forms.Form):
    """Cabecera de la compra; las líneas llegan en `items` (JSON) desde la pantalla."""

    PAGO = [("caja", "Pagado de mi caja"), ("fuera", "Pagado fuera de caja (transferencia, Yape…)"), ("credito", "Queda por pagar (al crédito)")]

    proveedor = forms.ModelChoiceField(queryset=Proveedor.objects.filter(activo=True), empty_label="Elige el proveedor…")
    documento = forms.ChoiceField(choices=Compra.Documento.choices, initial=Compra.Documento.FACTURA)
    serie = forms.CharField(max_length=4, required=False, widget=forms.TextInput(attrs={"placeholder": "F001", "style": "text-transform: uppercase"}))
    numero = forms.CharField(label="Número", max_length=12, required=False, widget=forms.TextInput(attrs={"placeholder": "123", "inputmode": "numeric"}))
    fecha = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    pago = forms.ChoiceField(label="¿Cómo se paga?", choices=PAGO, widget=forms.RadioSelect)
    vence = forms.DateField(label="Vence", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                            help_text="Vacío = según el plazo del proveedor.")
    nota = forms.CharField(max_length=200, required=False)
    items = forms.CharField(widget=forms.HiddenInput)
    token = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, puede_caja=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not puede_caja:
            self.fields["pago"].choices = [c for c in self.PAGO if c[0] != "caja"]


class PagoForm(forms.Form):
    monto = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={**DINERO, "class": "text-end"}))
    origen = forms.ChoiceField(label="¿De dónde sale?", widget=forms.RadioSelect,
                               choices=[("caja", "De mi caja"), ("fuera", "Fuera de caja (transferencia, Yape…)")])
    dia = forms.DateField(label="Fecha (fuera de caja)", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, puede_caja=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not puede_caja:
            self.fields["origen"].choices = [c for c in self.fields["origen"].choices if c[0] != "caja"]
