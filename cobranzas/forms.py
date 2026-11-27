from django import forms
from django.utils import timezone

from .models import Config, Inscripcion, Plan


class PlanForm(forms.ModelForm):
    aplicar_inscritos = forms.BooleanField(
        required=False, label="Cobrar el precio nuevo a los inscritos",
        help_text="Solo a quienes pagan el precio del plan (los que tienen precio especial o beca se quedan como están), "
                  "desde su próxima cuota sin pagar. Después te muestra la lista para avisarles por WhatsApp.")

    class Meta:
        model = Plan
        fields = ["nombre", "precio", "frecuencia", "num_cuotas", "matricula", "duracion_dias", "clases", "descripcion", "activo", "orden"]
        widgets = {"precio": forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal"}),
                   "matricula": forms.NumberInput(attrs={"step": "0.10", "inputmode": "decimal"})}

    def clean(self):
        d = super().clean()
        d["duracion_dias"] = d.get("duracion_dias") or 0
        if "clases" in self.fields:
            d["clases"] = d.get("clases") or 0
        if d.get("frecuencia") == Plan.Frecuencia.UNICO:
            d["num_cuotas"] = 0
        elif d.get("duracion_dias"):
            d["duracion_dias"] = 0  # la vigencia de los demás planes sale de sus cuotas
        return d

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Ajustes

        if not Ajustes.cargar().usa_ingreso:  # sin control de ingreso no hay cómo contar las clases
            self.fields.pop("clases")
        if not self.instance.pk:  # al crear un plan no hay inscritos
            self.fields.pop("aplicar_inscritos")
        for c in ("duracion_dias", "clases"):
            if c in self.fields:
                self.fields[c].required = False


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["dias_aviso", "mora_activa", "mora_monto", "dias_gracia", "dias_tolerancia", "congelar_dias"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Ajustes

        if not Ajustes.cargar().usa_ingreso:  # opciones de gimnasio: solo con Control de ingreso
            self.fields.pop("dias_tolerancia")
        for c in ("dias_tolerancia", "congelar_dias"):
            if c in self.fields:
                self.fields[c].required = False

    def clean(self):
        d = super().clean()
        for c in ("dias_tolerancia", "congelar_dias"):
            if c in self.fields and d.get(c) is None:
                d[c] = getattr(self.instance, c)
        return d


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
