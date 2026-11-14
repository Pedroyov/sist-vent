from django import forms
from django.db.models import Count, Q

from core.forms import FECHA
from core.models import Seccion

from .models import Alumno, AlumnoApoderado, Apoderado, Matricula, TipoDocumento, validar_documento


class SeccionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, s):
        ocupadas = getattr(s, "ocupadas", None)
        extra = f" ({ocupadas}/{s.vacantes})" if ocupadas is not None else ""
        return f"{s.grado.nivel} · {s.grado.nombre} \"{s.nombre}\" – {s.get_turno_display()}{extra}"


def secciones_de(anio):
    return (
        Seccion.objects.filter(anio_lectivo=anio)
        .select_related("grado__nivel")
        .annotate(ocupadas=Count("matriculas", filter=Q(matriculas__estado=Matricula.Estado.MATRICULADO)))
        .order_by("grado__nivel__orden", "grado__orden", "nombre")
    )


class AlumnoForm(forms.ModelForm):
    class Meta:
        model = Alumno
        fields = [
            "tipo_documento", "numero_documento", "codigo",
            "apellido_paterno", "apellido_materno", "nombres",
            "fecha_nacimiento", "sexo", "direccion", "foto", "observaciones",
        ]
        widgets = {
            "fecha_nacimiento": FECHA,
            "observaciones": forms.Textarea(attrs={"rows": 2}),
            "foto": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "numero_documento": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        }

    def clean_numero_documento(self):
        return (self.cleaned_data["numero_documento"] or "").strip().upper()


class MatriculaForm(forms.ModelForm):
    seccion = SeccionChoiceField(queryset=Seccion.objects.none(), label="Grado y sección")

    class Meta:
        model = Matricula
        fields = ["seccion", "tipo", "fecha", "estado", "observacion"]
        widgets = {"fecha": FECHA}

    def __init__(self, *args, anio=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.anio = anio or getattr(self.instance, "anio_lectivo", None)
        self.fields["seccion"].queryset = secciones_de(self.anio)
        if self.instance.pk is None:
            # al matricular, el estado siempre empieza como "Matriculado"
            del self.fields["estado"]

    def clean_seccion(self):
        seccion = self.cleaned_data["seccion"]
        cambia = self.instance.pk is None or self.instance.seccion_id != seccion.pk
        if cambia:
            ocupadas = seccion.matriculas.filter(estado=Matricula.Estado.MATRICULADO).count()
            if ocupadas >= seccion.vacantes:
                raise forms.ValidationError(
                    f"La sección está llena ({ocupadas}/{seccion.vacantes}). Aumenta las vacantes en Configuración o elige otra."
                )
        return seccion


class ApoderadoForm(forms.ModelForm):
    class Meta:
        model = Apoderado
        fields = ["tipo_documento", "numero_documento", "apellidos", "nombres", "celular", "celular2", "email", "direccion", "ocupacion"]
        widgets = {
            "numero_documento": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
            "celular": forms.TextInput(attrs={"inputmode": "tel"}),
            "celular2": forms.TextInput(attrs={"inputmode": "tel"}),
        }


class VinculoApoderadoForm(forms.Form):
    """
    Agrega un apoderado a un alumno. Si el documento ya existe (por ejemplo, es
    apoderado de un hermano), se reutiliza esa persona y se actualizan sus datos.
    """

    tipo_documento = forms.ChoiceField(label="Tipo de documento", choices=TipoDocumento.choices, initial=TipoDocumento.DNI)
    numero_documento = forms.CharField(
        label="N° de documento", max_length=15,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )
    apellidos = forms.CharField(max_length=100)
    nombres = forms.CharField(max_length=100)
    celular = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={"inputmode": "tel"}), help_text="Para llamadas y WhatsApp")
    email = forms.EmailField(label="Correo", required=False)
    parentesco = forms.ChoiceField(choices=AlumnoApoderado.Parentesco.choices, initial=AlumnoApoderado.Parentesco.MADRE)
    responsable_pago = forms.BooleanField(label="Responsable de pagos", required=False, initial=True)

    def __init__(self, *args, alumno=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.alumno = alumno

    def clean(self):
        datos = super().clean()
        tipo, numero = datos.get("tipo_documento"), (datos.get("numero_documento") or "").strip().upper()
        datos["numero_documento"] = numero
        if numero:
            try:
                validar_documento(tipo, numero)
            except forms.ValidationError as e:
                self.add_error("numero_documento", e.message_dict["numero_documento"])
        if numero and self.alumno and self.alumno.pk:
            if self.alumno.vinculos.filter(apoderado__numero_documento=numero).exists():
                self.add_error("numero_documento", "Esta persona ya es apoderado de este alumno.")
        return datos

    def guardar(self, alumno):
        d = self.cleaned_data
        apoderado, _ = Apoderado.objects.get_or_create(
            numero_documento=d["numero_documento"],
            defaults={"tipo_documento": d["tipo_documento"], "nombres": d["nombres"], "apellidos": d["apellidos"]},
        )
        apoderado.tipo_documento = d["tipo_documento"]
        apoderado.nombres = d["nombres"]
        apoderado.apellidos = d["apellidos"]
        if d.get("celular"):
            apoderado.celular = d["celular"]
        if d.get("email"):
            apoderado.email = d["email"]
        apoderado.save()
        responsable = d.get("responsable_pago") or not alumno.vinculos.exists()
        return AlumnoApoderado.objects.create(
            alumno=alumno, apoderado=apoderado, parentesco=d["parentesco"], responsable_pago=responsable
        )


class EditarVinculoForm(forms.ModelForm):
    class Meta:
        model = AlumnoApoderado
        fields = ["parentesco", "responsable_pago"]


class ImportarForm(forms.Form):
    archivo = forms.FileField(
        label="Archivo Excel (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def clean_archivo(self):
        f = self.cleaned_data["archivo"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("El archivo debe ser .xlsx (Excel). Si es .xls, ábrelo en Excel y guárdalo como .xlsx.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("El archivo es muy grande (máximo 5 MB).")
        return f
