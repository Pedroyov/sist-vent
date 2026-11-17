"""Vistas de configuración: datos del negocio, usuarios, roles y módulos."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import UsuarioForm
from .permisos import CODIGOS, MODULOS, NOMBRE_MODULO, PERMISOS, acceso_total, acceso_total_requerido, permiso_requerido
from .roles import roles_disponibles

User = get_user_model()


def _form(request, form, titulo, cancelar, breadcrumb=None, subtitulo=""):
    return render(
        request,
        "core/form.html",
        {"form": form, "titulo": titulo, "subtitulo": subtitulo, "cancelar": cancelar, "breadcrumb": breadcrumb or []},
    )


# --- Usuarios ---------------------------------------------------------------

@permiso_requerido("config.usuarios")
def usuario_lista(request):
    usuarios = User.objects.prefetch_related("groups").order_by("-is_active", "first_name", "last_name")
    rol = request.GET.get("rol", "")
    roles = roles_disponibles()
    if rol in roles:
        usuarios = usuarios.filter(groups__name=rol)
    return render(request, "core/config/usuario_lista.html", {"usuarios": usuarios, "roles": roles, "rol": rol})


@permiso_requerido("config.usuarios")
def usuario_form(request, pk=None):
    usuario = get_object_or_404(User, pk=pk) if pk else None
    if usuario and usuario.is_superuser and not request.user.is_superuser:
        messages.error(request, "Solo un administrador puede editar a otro administrador.")
        return redirect("core:usuario_lista")
    form = UsuarioForm(request.POST or None, instance=usuario)
    form.puede_dar_direccion = acceso_total(request.user)
    if request.method == "POST" and form.is_valid():
        if usuario == request.user and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "No puedes desactivar tu propio usuario.")
        else:
            u = form.save()
            messages.success(request, f"Usuario «{u.username}» guardado.")
            return redirect("core:usuario_lista")
    return _form(
        request,
        form,
        f"Editar usuario {usuario.username}" if usuario else "Nuevo usuario",
        reverse("core:usuario_lista"),
        [("Usuarios", reverse("core:usuario_lista"))],
    )


# --- Roles, permisos y módulos ----------------------------------------------

def _grupos_roles():
    from django.contrib.auth.models import Group

    from .permisos import ROLES_BASE

    grupos = list(Group.objects.filter(permisos_sis__isnull=False).select_related("permisos_sis")
                  .annotate(n_usuarios=Count("user", filter=models.Q(user__is_active=True))))
    grupos.sort(key=lambda g: (ROLES_BASE.index(g.name) if g.name in ROLES_BASE else 99, g.name.lower()))
    for g in grupos:
        g.base = g.name in ROLES_BASE
        g.total = g.name == ROLES_BASE[0]
        g.marcados = set(CODIGOS) if g.total else set(g.permisos_sis.permisos or [])
    return grupos


@acceso_total_requerido
def roles(request):
    from .models import Ajustes

    grupos = _grupos_roles()
    ajustes = Ajustes.cargar()
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "permisos":
            for g in grupos:
                if g.total:
                    continue
                marcados = [c for c in request.POST.getlist(f"p_{g.pk}") if c in CODIGOS]
                g.permisos_sis.permisos = [c for c in CODIGOS if c in marcados]
                g.permisos_sis.save()
            messages.success(request, "Permisos guardados. Se aplican desde la siguiente pantalla que abra cada usuario.")
        return redirect("core:roles")

    from .permisos import modulos_activos

    inactivos = set(ajustes.modulos_inactivos)
    activos = modulos_activos(ajustes)
    secciones = []
    for mod in ["ventas", "productos", *[m[0] for m in MODULOS], "config"]:
        if mod not in activos:
            continue  # los módulos que el administrador desactivó no se muestran
        secciones.append({
            "codigo": mod, "nombre": NOMBRE_MODULO[mod], "inactivo": False,
            "permisos": [{"codigo": p[0], "texto": p[2]} for p in PERMISOS if p[1] == mod],
        })
    return render(request, "core/config/roles.html", {
        "grupos": grupos, "secciones": secciones,
        "modulos": [{"codigo": m[0], "nombre": m[1], "icono": m[2], "texto": m[3], "activo": m[0] not in inactivos} for m in MODULOS],
    })


@acceso_total_requerido
def rol_form(request, pk=None):
    from django import forms as f
    from django.contrib.auth.models import Group

    from .models import PermisosRol
    from .permisos import ROLES_BASE

    grupo = get_object_or_404(Group, pk=pk, permisos_sis__isnull=False) if pk else None
    if grupo and grupo.name == ROLES_BASE[0]:
        messages.info(request, "Administración siempre tiene acceso total; no se puede modificar.")
        return redirect("core:roles")

    class RolForm(f.Form):
        nombre = f.CharField(label="Nombre del rol", max_length=60, help_text="Por ejemplo: Mozo, Almacén, Estilista, Supervisor.")
        descripcion = f.CharField(label="Descripción", max_length=150, required=False)
        copiar = f.ChoiceField(label="Empezar con los permisos de", required=False, choices=[("", "Ninguno (marcarlos después)")] + [
            (g.pk, g.name) for g in Group.objects.filter(permisos_sis__isnull=False).order_by("name")])

        def clean_nombre(self):
            n = " ".join(self.cleaned_data["nombre"].split())
            if Group.objects.filter(name__iexact=n).exclude(pk=getattr(grupo, "pk", None)).exists():
                raise f.ValidationError("Ya existe un rol con ese nombre.")
            if grupo and grupo.name in ROLES_BASE and n != grupo.name:
                raise f.ValidationError("Los roles que vienen con el sistema no se pueden renombrar.")
            return n

    inicial = {"nombre": grupo.name, "descripcion": grupo.permisos_sis.descripcion} if grupo else {}
    form = RolForm(request.POST or None, initial=inicial)
    if grupo:
        del form.fields["copiar"]
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            if grupo:
                grupo.name = d["nombre"]
                grupo.save()
                grupo.permisos_sis.descripcion = d["descripcion"]
                grupo.permisos_sis.save()
            else:
                grupo = Group.objects.create(name=d["nombre"])
                base = PermisosRol.objects.filter(grupo_id=d.get("copiar") or 0).first()
                permisos = list(CODIGOS) if base and base.grupo.name == ROLES_BASE[0] else (base.permisos if base else [])
                PermisosRol.objects.create(grupo=grupo, descripcion=d["descripcion"], permisos=list(permisos))
        messages.success(request, f"Rol «{grupo.name}» guardado. Marca sus permisos en la tabla.")
        return redirect(reverse("core:roles") + f"#rol-{grupo.pk}")
    return _form(request, form, f"Editar rol {grupo.name}" if grupo else "Nuevo rol", reverse("core:roles"),
                 [("Roles y permisos", reverse("core:roles"))])


@acceso_total_requerido
@require_POST
def rol_eliminar(request, pk):
    from django.contrib.auth.models import Group

    from .permisos import ROLES_BASE

    grupo = get_object_or_404(Group, pk=pk, permisos_sis__isnull=False)
    if grupo.name in ROLES_BASE:
        messages.error(request, "Los roles que vienen con el sistema no se pueden eliminar.")
    else:
        n = grupo.user_set.count()
        nombre = grupo.name
        grupo.delete()
        messages.success(request, f"Rol «{nombre}» eliminado." + (f" {n} usuario(s) lo tenían: revisa que tengan otro rol." if n else ""))
    return redirect("core:roles")


# --- Datos del negocio ----------------------------------------------------------

@permiso_requerido("config.negocio")
def datos_negocio(request):
    from .forms import DatosNegocioForm
    from .models import Ajustes

    ajustes = Ajustes.cargar()
    logo_antes = ajustes.logo.name if ajustes.logo else ""
    rubro_antes = ajustes.rubro
    form = DatosNegocioForm(request.POST or None, request.FILES or None, instance=ajustes)
    if request.method == "POST" and form.is_valid():
        a = form.save()
        if a.logo and a.logo.name != logo_antes:
            try:
                a.generar_iconos()
            except Exception:  # imagen dañada o formato raro
                a.logo = logo_antes or None
                a.save()
                messages.error(request, "No se pudo procesar el logo. Prueba con otra imagen PNG o JPG.")
                return redirect("core:datos_negocio")
            a.save(update_fields=["version_logo"])
        if not a.logo and a.version_logo:
            a.version_logo = 0
            a.save(update_fields=["version_logo"])
        from .models import Rubro

        if a.rubro != rubro_antes:  # otro tipo de negocio: se ajustan las funciones (lo que ya se usa no se apaga)
            from .rubros import aplicar

            encendidas, apagadas = aplicar(a)
            if encendidas or apagadas:
                messages.info(request, f"Ajustado para {a.get_rubro_display().lower()}:"
                              + (f" se activó {', '.join(encendidas)}." if encendidas else "")
                              + (f" Se ocultó {', '.join(apagadas)} (no se estaba usando)." if apagadas else ""))
        if a.rubro == Rubro.RESTAURANTE and "mesas" in a.modulos_inactivos:
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m != "mesas"]
            a.save(update_fields=["modulos_inactivos"])
            messages.info(request, "Se activó el módulo Mesas, porque el negocio es un restaurante.")
        if a.rubro == Rubro.ACADEMIA and ("cobranzas" in a.modulos_inactivos or "clientes" in a.modulos_inactivos):
            a.modulos_inactivos = [m for m in a.modulos_inactivos if m not in ("cobranzas", "clientes")]
            a.save(update_fields=["modulos_inactivos"])
            messages.info(request, "Se activó el módulo Cobranzas (mensualidades), porque el negocio es una academia o gimnasio.")
        messages.success(request, "Datos del negocio guardados. Si instalaste la app en el celular, el ícono nuevo puede tardar en aparecer (o reinstálala).")
        return redirect("core:datos_negocio")
    return render(request, "core/config/negocio.html", {"form": form, "c": ajustes})


# --- Módulos del sistema (solo el administrador principal) ----------------------

def _solo_administrador(vista):
    from functools import wraps

    from django.contrib.auth.views import redirect_to_login
    from django.core.exceptions import PermissionDenied

    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return envoltura


@_solo_administrador
def modulos(request):
    """El administrador principal (superusuario) decide qué módulos usa el negocio.
    Administración no puede cambiarlo: solo reparte permisos dentro de los módulos activos."""
    from .models import Ajustes

    ajustes = Ajustes.cargar()
    if request.method == "POST" and request.POST.get("accion") == "recomendado":
        from .rubros import aplicar

        encendidos, apagados = aplicar(ajustes, modulos=True)
        messages.success(request, f"Listo para {ajustes.get_rubro_display().lower()}."
                         + (f" Se activó: {', '.join(encendidos)}." if encendidos else "")
                         + (f" Se apagó: {', '.join(apagados)} (no tenía datos)." if apagados else "")
                         + ("" if encendidos or apagados else " Ya estaba así."))
        return redirect("core:modulos")
    if request.method == "POST":
        activos = set(request.POST.getlist("modulo"))
        ajustes.modulos_inactivos = [m[0] for m in MODULOS if m[0] not in activos]
        ajustes.save(update_fields=["modulos_inactivos"])
        apagados = [m[1] for m in MODULOS if m[0] in ajustes.modulos_inactivos]
        messages.success(request, "Módulos guardados." + (f" Desactivados: {', '.join(apagados)}." if apagados else " Todos activos."))
        return redirect("core:modulos")
    inactivos = set(ajustes.modulos_inactivos)
    from .rubros import perfil

    p = perfil(ajustes.rubro)
    return render(request, "core/config/modulos.html", {
        "rubro": ajustes.get_rubro_display(),
        "recomendado": [NOMBRE_MODULO[m[0]] for m in MODULOS if m[0] in p["encendido"]],
        "opcional": [NOMBRE_MODULO[m[0]] for m in MODULOS if m[0] in p["opcional"]],
        "difiere": any((m[0] in p["encendido"]) == (m[0] in inactivos) for m in MODULOS if m[0] in p["encendido"]),
        "modulos": [{"codigo": m[0], "nombre": m[1], "icono": m[2], "texto": m[3], "activo": m[0] not in inactivos,
                     "necesita": m[4], "necesita_nombre": NOMBRE_MODULO.get(m[4], "")} for m in MODULOS],
    })
