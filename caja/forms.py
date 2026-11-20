from decimal import Decimal

from django import forms

import re

from .models import MovimientoCaja, PuntoCaja, SesionCaja

DINERO = {"step": "0.10", "min": "0", "inputmode": "decimal"}


class AbrirForm(forms.Form):
    monto_inicial = forms.DecimalField(label="Efectivo con el que empiezas (sencillo)", min_value=Decimal("0"), decimal_places=2,
                                       widget=forms.NumberInput(attrs={**DINERO, "autofocus": True, "class": "form-control-lg"}))
    nota = forms.CharField(label="Nota", max_length=200, required=False)
    punto = forms.ModelChoiceField(label="¿En qué caja estás?", queryset=PuntoCaja.objects.none(), required=False,
                                   widget=forms.RadioSelect, empty_label=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        activos = PuntoCaja.objects.filter(activo=True)
        if activos.count() > 1:
            self.fields["punto"].queryset = activos
            self.fields["punto"].required = True
            ocupadas = {s.punto_id: s.usuario for s in SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA, punto__isnull=False)
                        .select_related("usuario")}
            self.fields["punto"].label_from_instance = lambda p: p.nombre + (
                f" (abierta por {ocupadas[p.pk].first_name or ocupadas[p.pk].username})" if p.pk in ocupadas else "")
        else:
            del self.fields["punto"]  # una sola caja (o ninguna): se usa sola


class PuntoCajaForm(forms.ModelForm):
    class Meta:
        model = PuntoCaja
        fields = ["nombre", "serie_boleta", "serie_factura", "serie_nc_boleta", "serie_nc_factura", "activo"]
        widgets = {c: forms.TextInput(attrs={"maxlength": 4, "style": "text-transform: uppercase", "placeholder": "General"})
                   for c in ["serie_boleta", "serie_factura", "serie_nc_boleta", "serie_nc_factura"]}

    def _serie(self, campo, letra):
        v = self.cleaned_data.get(campo, "").strip().upper()
        if v and not re.fullmatch(rf"{letra}[A-Z0-9]{{3}}", v):
            raise forms.ValidationError(f"4 caracteres que empiezan con {letra} (ej.: {letra}002).")
        return v

    def clean_serie_boleta(self):
        return self._serie("serie_boleta", "B")

    def clean_serie_factura(self):
        return self._serie("serie_factura", "F")

    def clean_serie_nc_boleta(self):
        return self._serie("serie_nc_boleta", "B")

    def clean_serie_nc_factura(self):
        return self._serie("serie_nc_factura", "F")

    def clean_nombre(self):
        return " ".join(self.cleaned_data["nombre"].split())


class MovimientoForm(forms.ModelForm):
    """Sacar o meter dinero de la caja. Con «Pagos al personal», el pago a personal se liga a la persona."""

    class Meta:
        model = MovimientoCaja
        fields = ["categoria", "persona", "monto", "concepto"]
        widgets = {"monto": forms.NumberInput(attrs={**DINERO, "autofocus": True})}

    def __init__(self, *args, tipo=MovimientoCaja.Tipo.EGRESO, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Ajustes
        from personal.models import Persona

        C = MovimientoCaja.Categoria
        if tipo == MovimientoCaja.Tipo.INGRESO:
            opciones = [C.SENCILLO, C.OTRO]
        else:
            opciones = self.EGRESOS
        self.fields["categoria"].choices = [(c.value, c.label) for c in opciones]
        if tipo == MovimientoCaja.Tipo.EGRESO and Ajustes.cargar().usa_pagos:
            self.fields["persona"].queryset = Persona.objects.filter(activo=True)
            self.fields["persona"].empty_label = "—"
            self.fields["persona"].help_text = "Solo para «Pago o adelanto a personal»."
        else:
            del self.fields["persona"]

    EGRESOS = [MovimientoCaja.Categoria.PROVEEDOR, MovimientoCaja.Categoria.GASTO, MovimientoCaja.Categoria.PERSONAL,
               MovimientoCaja.Categoria.RETIRO, MovimientoCaja.Categoria.DEVOLUCION, MovimientoCaja.Categoria.OTRO]

    def clean(self):
        d = super().clean()
        if "persona" in self.fields and d.get("categoria") == MovimientoCaja.Categoria.PERSONAL and not d.get("persona"):
            self.add_error("persona", "Elige a quién se le paga.")
        return d


class GastoForm(MovimientoForm):
    """Gasto pagado fuera de caja (transferencia, Yape, dinero del dueño): no descuadra ninguna caja."""

    dia = forms.DateField(label="Fecha", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    class Meta(MovimientoForm.Meta):
        fields = ["categoria", "persona", "monto", "concepto"]

    EGRESOS = [MovimientoCaja.Categoria.PROVEEDOR, MovimientoCaja.Categoria.GASTO, MovimientoCaja.Categoria.PERSONAL,
               MovimientoCaja.Categoria.DEVOLUCION, MovimientoCaja.Categoria.OTRO]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, tipo=MovimientoCaja.Tipo.EGRESO, **kwargs)
        self.order_fields(["dia"])
        self.fields["concepto"].help_text = 'Ej.: "Alquiler de noviembre, transferencia BCP".'


class CerrarForm(forms.Form):
    contado = forms.DecimalField(label="Efectivo contado en el cajón", min_value=Decimal("0"), decimal_places=2,
                                 widget=forms.NumberInput(attrs={**DINERO, "class": "form-control-lg text-end"}))
    queda = forms.DecimalField(label="¿Cuánto dejas en el cajón para el siguiente turno?", min_value=Decimal("0"), decimal_places=2,
                               required=False, widget=forms.NumberInput(attrs={**DINERO, "class": "text-end"}),
                               help_text="El sencillo para dar vuelto. Lo demás se retira (el dueño o el banco). Vacío = se queda todo.")

    def clean(self):
        d = super().clean()
        if d.get("queda") is not None and d.get("contado") is not None and d["queda"] > d["contado"]:
            self.add_error("queda", "No puedes dejar más de lo que contaste.")
        return d

    nota = forms.CharField(label="Nota del cierre", max_length=300, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ej.: faltan S/ 2, se dio mal un vuelto"}))
