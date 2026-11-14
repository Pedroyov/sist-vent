from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password

from .models import AnioLectivo, Grado, ModoAsistencia, Periodo, Seccion
from .roles import DIRECCION, DOCENTE, roles_disponibles

User = get_user_model()

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuario",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "class": "form-control"}),
    )
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "form-control"}),
    )

    # Contra adivinar contraseñas: tras 5 intentos fallidos con un usuario (o 30 desde una misma
    # conexión) hay que esperar 15 minutos.
    MAX_USUARIO, MAX_IP, ESPERA = 5, 30, 15 * 60

    def _claves(self):
        from hashlib import sha256

        usuario = (self.data.get("username") or "").strip().lower()
        ip = (self.request.META.get("REMOTE_ADDR", "") if self.request else "")
        return ("login:u:" + sha256(usuario.encode()).hexdigest()[:32], "login:ip:" + ip)

    def clean(self):
        from django.core.cache import cache

        k_usuario, k_ip = self._claves()
        if cache.get(k_usuario, 0) >= self.MAX_USUARIO or cache.get(k_ip, 0) >= self.MAX_IP:
            raise forms.ValidationError(
                "Demasiados intentos fallidos. Por seguridad, espera 15 minutos o pide a Dirección que revise tu usuario.",
                code="bloqueado")
        try:
            datos = super().clean()
        except forms.ValidationError:
            for k in (k_usuario, k_ip):
                try:
                    cache.incr(k)
                except ValueError:
                    cache.set(k, 1, self.ESPERA)
            raise
        cache.delete(k_usuario)
        return datos


# --- Años y periodos --------------------------------------------------------

class AnioLectivoForm(forms.ModelForm):
    class Meta:
        model = AnioLectivo
        fields = ["anio", "fecha_inicio", "fecha_fin", "nombre", "activo"]
        widgets = {"fecha_inicio": FECHA, "fecha_fin": FECHA}


class PeriodoForm(forms.ModelForm):
    class Meta:
        model = Periodo
        fields = ["numero", "nombre", "fecha_inicio", "fecha_fin"]
        widgets = {"fecha_inicio": FECHA, "fecha_fin": FECHA}

    def __init__(self, *args, anio_lectivo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.anio_lectivo = anio_lectivo or getattr(self.instance, "anio_lectivo", None)

    def clean_numero(self):
        numero = self.cleaned_data["numero"]
        qs = Periodo.objects.filter(anio_lectivo=self.anio_lectivo, numero=numero).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un periodo con ese número en este año.")
        return numero


class GenerarPeriodosForm(forms.Form):
    TIPOS = [("4", "4 bimestres"), ("3", "3 trimestres")]
    tipo = forms.ChoiceField(label="Organización del año", choices=TIPOS, initial="4")


# --- Secciones --------------------------------------------------------------

def docentes_qs():
    return User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class UsuarioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


class SeccionForm(forms.ModelForm):
    tutor = UsuarioChoiceField(queryset=User.objects.none(), required=False, label="Tutor(a)")

    class Meta:
        model = Seccion
        fields = ["grado", "nombre", "turno", "tutor", "vacantes", "modo_asistencia"]

    def __init__(self, *args, anio_lectivo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.anio_lectivo = anio_lectivo or getattr(self.instance, "anio_lectivo", None)
        self.fields["grado"].queryset = Grado.objects.select_related("nivel")
        self.fields["tutor"].queryset = docentes_qs()

    def clean(self):
        datos = super().clean()
        grado, nombre = datos.get("grado"), datos.get("nombre")
        if grado and nombre:
            qs = Seccion.objects.filter(anio_lectivo=self.anio_lectivo, grado=grado, nombre__iexact=nombre)
            if qs.exclude(pk=self.instance.pk).exists():
                self.add_error("nombre", "Esa sección ya existe para este grado en este año.")
        return datos


class CrearSeccionesForm(forms.Form):
    grados = forms.ModelMultipleChoiceField(
        queryset=Grado.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Grados",
    )
    secciones = forms.CharField(
        label="Secciones",
        initial="A",
        help_text='Separadas por coma. Ej.: "A" o "A, B".',
    )
    turno = forms.ChoiceField(choices=Seccion.Turno.choices, initial=Seccion.Turno.MANANA)
    vacantes = forms.IntegerField(min_value=1, initial=30)
    modo_asistencia = forms.ChoiceField(
        label="Asistencia",
        choices=[("AUTO", "Automático: por curso en secundaria, diaria en el resto")] + list(ModoAsistencia.choices),
        initial="AUTO",
        required=False,
    )

    def clean_modo_asistencia(self):
        return self.cleaned_data.get("modo_asistencia") or "AUTO"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grados"].queryset = Grado.objects.select_related("nivel")

    def clean_secciones(self):
        nombres = [s.strip().upper() for s in self.cleaned_data["secciones"].split(",") if s.strip()]
        if not nombres:
            raise forms.ValidationError("Indica al menos una sección.")
        return list(dict.fromkeys(nombres))


# --- Usuarios ---------------------------------------------------------------

class UsuarioForm(forms.ModelForm):
    rol = forms.MultipleChoiceField(
        label="Rol", widget=forms.CheckboxSelectMultiple, initial=[DOCENTE],
        help_text="Puedes marcar más de uno (por ejemplo, un docente que también cobra). Lo que puede hacer cada rol se define en Roles y permisos.",
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), required=False)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]
        labels = {"username": "Usuario", "first_name": "Nombres", "last_name": "Apellidos", "email": "Correo", "is_active": "Activo"}
        help_texts = {"username": "Con este nombre ingresará al sistema. Sin espacios.", "is_active": "Desmarca para bloquear el acceso sin borrar al usuario."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.es_nuevo = self.instance.pk is None
        self.fields["rol"].choices = [(r, r) for r in roles_disponibles()]
        self.puede_dar_direccion = True
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        if self.es_nuevo:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
        else:
            self.fields["password1"].help_text = "Déjalo en blanco para mantener la contraseña actual."
            roles = list(self.instance.groups.filter(permisos_sis__isnull=False).values_list("name", flat=True))
            if roles:
                self.initial["rol"] = roles

    def clean(self):
        datos = super().clean()
        if not self.puede_dar_direccion:
            tenia = not self.es_nuevo and self.instance.groups.filter(name=DIRECCION).exists()
            pide = DIRECCION in (datos.get("rol") or [])
            if pide != tenia:
                self.add_error("rol", "Solo Dirección puede dar o quitar el rol Dirección.")
            if not self.es_nuevo and tenia:
                self.add_error(None, "Solo Dirección puede editar a un usuario de Dirección.")
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                try:
                    validate_password(p1, self.instance)
                except forms.ValidationError as e:
                    self.add_error("password1", e)
        return datos

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            otros = user.groups.filter(permisos_sis__isnull=False)
            user.groups.remove(*otros)
            user.groups.add(*Group.objects.filter(name__in=self.cleaned_data["rol"]))
        return user


# --- Datos del colegio ---------------------------------------------------------

class DatosColegioForm(forms.ModelForm):
    class Meta:
        from .models import Ajustes

        model = Ajustes
        fields = ["nombre", "nombre_corto", "lema", "logo", "ruc", "codigo_modular", "ugel", "resolucion",
                  "direccion", "distrito", "telefono", "whatsapp", "email", "web", "director", "nota_recibo", "color"]
        widgets = {
            "logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "ruc": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 11}),
            "telefono": forms.TextInput(attrs={"inputmode": "tel"}),
            "whatsapp": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "987654321"}),
        }

    def clean_ruc(self):
        ruc = self.cleaned_data["ruc"].strip()
        if ruc and (not ruc.isdigit() or len(ruc) != 11):
            raise forms.ValidationError("El RUC tiene 11 dígitos.")
        return ruc

    def clean_color(self):
        import re

        c = (self.cleaned_data.get("color") or "#0d6efd").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise forms.ValidationError("Color no válido.")
        return c

    def clean_nombre_corto(self):
        return self.cleaned_data["nombre_corto"].strip()
