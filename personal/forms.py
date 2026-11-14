import re
import secrets
import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core.forms import FECHA
from core.roles import DIRECCION, DOCENTE, TESORERIA, roles_disponibles

from .models import DIAS_LABORALES, HorarioTrabajador, Trabajador

User = get_user_model()

ROL_POR_CARGO = {
    Trabajador.Cargo.DIRECCION: DIRECCION,
    Trabajador.Cargo.TESORERIA: TESORERIA,
    Trabajador.Cargo.ADMINISTRATIVO: TESORERIA,
}


def sugerir_usuario(nombres, apellidos):
    def limpio(t):
        t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z]", "", t)
    base = (limpio(nombres)[:1] + limpio((apellidos or "").split(" ")[0])) or "usuario"
    nombre, i = base, 2
    while User.objects.filter(username=nombre).exists():
        nombre, i = f"{base}{i}", i + 1
    return nombre


def clave_inicial():
    """Clave temporal fácil de dictar pero difícil de adivinar (p. ej. Colegio-K7M4Q9)."""
    letras = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para no confundir
    return "Colegio-" + "".join(secrets.choice(letras) for _ in range(6))


class TrabajadorForm(forms.ModelForm):
    dar_acceso = forms.BooleanField(label="Darle acceso al sistema", required=False)
    rol = forms.ChoiceField(label="Rol en el sistema", choices=[], initial=DOCENTE, required=False)

    class Meta:
        model = Trabajador
        fields = [
            "numero_documento", "apellidos", "nombres", "cargo", "especialidad", "celular", "email", "fecha_ingreso", "fecha_nacimiento",
            "modalidad", "sueldo", "pago_hora", "horas_extra_semana", "horas_max_semana", "cuenta_bancaria", "observaciones", "activo", "usuario",
        ]
        widgets = {
            "fecha_ingreso": FECHA,
            "fecha_nacimiento": FECHA,
            "observaciones": forms.Textarea(attrs={"rows": 2}),
            "numero_documento": forms.TextInput(attrs={"inputmode": "numeric"}),
            "celular": forms.TextInput(attrs={"inputmode": "tel"}),
            "sueldo": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
            "pago_hora": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
            "horas_extra_semana": forms.NumberInput(attrs={"step": "0.5", "inputmode": "decimal"}),
        }
        labels = {"usuario": "Usuario del sistema ya existente"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].choices = [("", "Según el cargo")] + [(r, r) for r in roles_disponibles()]
        libres = User.objects.filter(trabajador__isnull=True)
        if self.instance.usuario_id:
            libres = libres | User.objects.filter(pk=self.instance.usuario_id)
        self.fields["usuario"].queryset = libres.order_by("first_name", "username")
        self.fields["usuario"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.username})"
        self.fields["usuario"].required = False

    def clean_numero_documento(self):
        return (self.cleaned_data["numero_documento"] or "").strip().upper()

    def clean(self):
        d = super().clean()
        if d.get("modalidad") == Trabajador.Modalidad.MENSUAL and not d.get("sueldo"):
            self.add_error("sueldo", "Indica el sueldo mensual (o cambia la modalidad a pago por hora).")
        if d.get("modalidad") == Trabajador.Modalidad.POR_HORA and not d.get("pago_hora"):
            self.add_error("pago_hora", "Indica cuánto se paga por hora.")
        if d.get("dar_acceso") and d.get("usuario"):
            self.add_error("dar_acceso", "Ya elegiste un usuario existente; no hace falta crear otro.")
        return d

    def save(self, commit=True):
        t = super().save(commit=False)
        self.clave = None
        if self.cleaned_data.get("dar_acceso") and not t.usuario_id:
            usuario = User.objects.create(
                username=sugerir_usuario(t.nombres, t.apellidos), first_name=t.nombres.title()[:150],
                last_name=t.apellidos.title()[:150], email=t.email,
            )
            self.clave = clave_inicial()
            usuario.set_password(self.clave)
            usuario.save()
            rol = self.cleaned_data.get("rol") or ROL_POR_CARGO.get(t.cargo, DOCENTE)
            usuario.groups.add(Group.objects.get(name=rol))
            t.usuario = usuario
        if commit:
            t.save()
        return t


class HorarioForm(forms.ModelForm):
    class Meta:
        model = HorarioTrabajador
        fields = ["dia", "inicio", "fin"]
        widgets = {"inicio": forms.TimeInput(attrs={"type": "time"}), "fin": forms.TimeInput(attrs={"type": "time"})}

    def clean(self):
        d = super().clean()
        if d.get("inicio") and d.get("fin") and d["fin"] <= d["inicio"]:
            self.add_error("fin", "Debe ser mayor que la hora de entrada.")
        return d


HorarioFormSet = forms.inlineformset_factory(
    Trabajador, HorarioTrabajador, form=HorarioForm, extra=0, can_delete=True,
)


class CopiarHorarioForm(forms.Form):
    """Atajo: mismo horario de lunes a viernes (o sábado)."""
    dias = forms.MultipleChoiceField(choices=DIAS_LABORALES, widget=forms.CheckboxSelectMultiple, initial=[1, 2, 3, 4, 5])
    inicio = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    fin = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
