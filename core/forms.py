from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password

from .roles import ADMINISTRACION, VENDEDOR, roles_disponibles

User = get_user_model()

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class UsuarioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


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
        return claves_ingreso(self.request, self.data.get("username"))

    def clean(self):
        cache = cache_seguridad()
        k_usuario, k_ip = self._claves()
        if bloqueado(self.request, self.data.get("username")):
            if not cache.get(k_usuario + ":anotado"):  # una vez por bloqueo, no en cada intento
                from .bitacora import anotar

                cache.set(k_usuario + ":anotado", 1, self.ESPERA)
                anotar("ingreso.bloqueado", f"Ingreso bloqueado para «{(self.data.get('username') or '').strip()[:40]}» por intentos fallidos")
            raise forms.ValidationError(
                "Demasiados intentos fallidos. Por seguridad, espera 15 minutos o pide al administrador que revise tu usuario.",
                code="bloqueado")
        try:
            datos = super().clean()
        except forms.ValidationError:
            contar_fallo(self.request, self.data.get("username"))
            raise
        cache.delete(k_usuario)
        return datos


def cache_seguridad():
    """Intentos fallidos de ingreso: en la base de datos, para que los vean todos los procesos y servidores."""
    from django.core.cache import caches

    return caches["seguridad"]


def claves_ingreso(request, usuario):
    from hashlib import sha256

    from .utils import ip_cliente

    usuario = (usuario or "").strip().lower()
    return ("login:u:" + sha256(usuario.encode()).hexdigest()[:32], "login:ip:" + ip_cliente(request))


def contar_fallo(request, usuario):
    """Un intento fallido (contraseña o código del celular) cuenta para el bloqueo de ese usuario y de esa conexión."""
    cache = cache_seguridad()
    for k in claves_ingreso(request, usuario):
        try:
            cache.incr(k)
        except ValueError:
            cache.set(k, 1, LoginForm.ESPERA)


def bloqueado(request, usuario):
    cache = cache_seguridad()
    k_usuario, k_ip = claves_ingreso(request, usuario)
    return cache.get(k_usuario, 0) >= LoginForm.MAX_USUARIO or cache.get(k_ip, 0) >= LoginForm.MAX_IP


# --- Usuarios ---------------------------------------------------------------

class UsuarioForm(forms.ModelForm):
    rol = forms.MultipleChoiceField(
        label="Rol", widget=forms.CheckboxSelectMultiple, initial=[VENDEDOR],
        help_text="Puedes marcar más de uno (por ejemplo, un vendedor que también cobra). Lo que puede hacer cada rol se define en Roles y permisos.",
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
            tenia = not self.es_nuevo and self.instance.groups.filter(name=ADMINISTRACION).exists()
            pide = ADMINISTRACION in (datos.get("rol") or [])
            if pide != tenia:
                self.add_error("rol", "Solo Administración puede dar o quitar el rol Administración.")
            if not self.es_nuevo and tenia:
                self.add_error(None, "Solo Administración puede editar a un usuario de Administración.")
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


# --- Datos del negocio ---------------------------------------------------------

class DatosNegocioForm(forms.ModelForm):
    funciones = forms.MultipleChoiceField(label="Funciones que usa el negocio", required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
                                          help_text="Lo que no marques no aparece en las pantallas. No se borra nada: lo puedes volver a marcar.")
    metodos = forms.MultipleChoiceField(label="Métodos de pago que acepta", required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "btn-check"}),
                                        help_text="Solo los marcados aparecen al cobrar. El efectivo siempre está.")

    class Meta:
        from .models import Ajustes

        model = Ajustes
        fields = ["rubro", "nombre", "nombre_corto", "lema", "logo", "razon_social", "ruc",
                  "direccion", "distrito", "telefono", "whatsapp", "email", "web", "nota_ticket", "color",
                  "vender_sin_caja", "cierre_ciego", "propina_activa", "exigir_operacion", "descuentos_activos", "cortesias_activas",
                  "ticket_ancho", "imprimir_auto", "nivel_pedido", "delivery_costo"]
        widgets = {
            "nivel_pedido": forms.RadioSelect,
            "logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            "ruc": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 11}),
            "telefono": forms.TextInput(attrs={"inputmode": "tel"}),
            "whatsapp": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "987654321"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ventas.models import MetodoPago

        from .rubros import CODIGOS_FUNCIONES, FUNCIONES

        self.fields["funciones"].choices = [(c, n) for c, n, _ in FUNCIONES]
        self.fields["funciones"].initial = [c for c in CODIGOS_FUNCIONES if self.instance.usa(c)]
        self.explicacion_funciones = {c: t for c, _, t in FUNCIONES}
        self.fields["metodos"].choices = [(k, v) for k, v in MetodoPago.choices if k != MetodoPago.EFECTIVO]
        self.fields["metodos"].initial = [m for m in self.instance.metodos_aceptados if m != MetodoPago.EFECTIVO]
        if not self.instance.tiene_modulo("mesas"):
            del self.fields["cortesias_activas"]  # no se muestra: que no se apague sin querer
            if not self.instance.tiene_modulo("delivery") and self.instance.nivel_pedido == 1:
                del self.fields["nivel_pedido"]  # sin mesas ni delivery los pedidos son simples

    def save(self, commit=True):
        from ventas.models import MetodoPago

        from .rubros import CODIGOS_FUNCIONES

        self.instance.metodos_pago = [MetodoPago.EFECTIVO] + list(self.cleaned_data.get("metodos") or [])
        elegidas = set(self.cleaned_data.get("funciones") or [])
        self.instance.funciones_inactivas = [c for c in CODIGOS_FUNCIONES if c not in elegidas]
        return super().save(commit)

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
