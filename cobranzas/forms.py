from django import forms
from django.utils import timezone

from .models import Config, Inscripcion, Plan


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["nombre", "precio", "frecuencia", "num_cuotas", "matricula", "descripcion", "activo", "orden"]
        widgets = {"precio": forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal"}),
                   "matricula": forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal"})}

    def clean(self):
        d = super().clean()
        if d.get("frecuencia") == Plan.Frecuencia.UNICO:
            d["num_cuotas"] = 0
        return d


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["dias_aviso", "mora_activa", "mora_monto", "dias_gracia"]


class InscripcionForm(forms.Form):
    """Inscribir: el cliente se elige de la lista (cliente_id) o se escribe uno nuevo."""

    cliente_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    nombre = forms.CharField(label="Cliente (quien paga)", max_length=150, required=False)
    documento = forms.CharField(label="DNI / RUC", max_length=12, required=False)
    telefono = forms.CharField(label="Celular / WhatsApp", max_length=20, required=False)
    alumno = forms.CharField(label="Alumno o socio", max_length=120, required=False,
                             help_text="Solo si no es el mismo que paga (ej.: el hijo).")
    plan = forms.ModelChoiceField(label="Plan", queryset=Plan.objects.filter(activo=True), empty_label=None)
    inicio = forms.DateField(label="Empieza el", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    precio = forms.DecimalField(label="Precio de cada cuota", min_value=0, decimal_places=2, required=False,
                                widget=forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal"}),
                                help_text="Vacío = el del plan. Menos si tiene descuento o beca.")
    dia_pago = forms.IntegerField(label="Día de pago", min_value=1, max_value=31, required=False,
                                  help_text="Planes mensuales: día del mes en que vence. Vacío = el mismo día en que empieza.")
    cobrar_matricula = forms.BooleanField(label="Cobrar matrícula", required=False, initial=True)
    nota = forms.CharField(label="Nota", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].initial = timezone.localdate()


class EditarInscripcionForm(forms.ModelForm):
    class Meta:
        model = Inscripcion
        fields = ["alumno", "precio", "dia_pago", "nota"]
