"""Vistas de configuración del colegio: años lectivos, periodos, secciones y usuarios."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Count, ProtectedError, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    AnioLectivoForm,
    CrearSeccionesForm,
    GenerarPeriodosForm,
    PeriodoForm,
    SeccionForm,
    UsuarioForm,
)
from .models import AnioLectivo, Grado, ModoAsistencia, Nivel, Periodo, Seccion
from .permisos import CODIGOS, MODULOS, NOMBRE_MODULO, PERMISOS, acceso_total, acceso_total_requerido, permiso_requerido
from .roles import roles_disponibles

User = get_user_model()

ROMANOS = ["I", "II", "III", "IV", "V", "VI"]


def _form(request, form, titulo, cancelar, breadcrumb=None, subtitulo=""):
    return render(
        request,
        "core/form.html",
        {"form": form, "titulo": titulo, "subtitulo": subtitulo, "cancelar": cancelar, "breadcrumb": breadcrumb or []},
    )


# --- Años lectivos ----------------------------------------------------------

@permiso_requerido("config.colegio")
def configuracion(request):
    """Entrada del menú: va al año en curso, o a la lista si aún no hay ninguno."""
    anio = AnioLectivo.actual()
    if anio:
        from .permisos import puede

        if puede(request.user, "programacion.editar"):
            return redirect(reverse("academico:panel") + f"?anio={anio.pk}")
        return redirect("core:anio_detalle", pk=anio.pk)
    return redirect("core:anio_lista")


@permiso_requerido("config.colegio")
def anio_lista(request):
    anios = AnioLectivo.objects.annotate(n_secciones=Count("secciones", distinct=True), n_periodos=Count("periodos", distinct=True))
    return render(request, "core/config/anio_lista.html", {"anios": anios})


@permiso_requerido("config.colegio")
def anio_form(request, pk=None):
    anio = get_object_or_404(AnioLectivo, pk=pk) if pk else None
    if anio is None and not AnioLectivo.objects.exists():
        inicial = {"activo": True}
    else:
        inicial = {}
    form = AnioLectivoForm(request.POST or None, instance=anio, initial=inicial)
    if request.method == "POST" and form.is_valid():
        anio = form.save()
        messages.success(request, f"Año lectivo {anio} guardado.")
        return redirect("core:anio_detalle", pk=anio.pk)
    return _form(
        request,
        form,
        f"Editar año {anio}" if anio else "Nuevo año lectivo",
        reverse("core:anio_detalle", args=[anio.pk]) if anio else reverse("core:anio_lista"),
        [("Años lectivos", reverse("core:anio_lista"))],
    )


@permiso_requerido("config.colegio")
@require_POST
def anio_activar(request, pk):
    anio = get_object_or_404(AnioLectivo, pk=pk)
    anio.activo = True
    anio.save()
    messages.success(request, f"{anio} es ahora el año en curso.")
    return redirect("core:anio_detalle", pk=anio.pk)


@permiso_requerido("config.colegio")
def anio_detalle(request, pk):
    anio = get_object_or_404(AnioLectivo, pk=pk)
    secciones = (
        Seccion.objects.filter(anio_lectivo=anio)
        .select_related("grado__nivel", "tutor")
        .order_by("grado__orden", "nombre")
    )
    niveles = Nivel.objects.prefetch_related(
        Prefetch("grados", queryset=Grado.objects.prefetch_related(Prefetch("secciones", queryset=secciones, to_attr="secs")))
    )
    # Solo niveles y grados que tienen secciones en este año
    niveles = [
        (nivel, [g for g in nivel.grados.all() if g.secs])
        for nivel in niveles
    ]
    niveles = [(n, gs) for n, gs in niveles if gs]
    contexto = {
        "anio": anio,
        "anios": AnioLectivo.objects.all(),
        "periodos": anio.periodos.all(),
        "niveles": niveles,
        "total_secciones": secciones.count(),
        "total_vacantes": sum(s.vacantes for s in secciones),
        "form_generar": GenerarPeriodosForm(),
    }
    return render(request, "core/config/anio_detalle.html", contexto)


# --- Periodos ---------------------------------------------------------------

@permiso_requerido("config.colegio")
@require_POST
def periodos_generar(request, pk):
    anio = get_object_or_404(AnioLectivo, pk=pk)
    form = GenerarPeriodosForm(request.POST)
    if anio.periodos.exists():
        messages.warning(request, "Este año ya tiene periodos. Elimínalos primero si quieres generarlos de nuevo.")
    elif form.is_valid():
        n = int(form.cleaned_data["tipo"])
        tipo = "Bimestre" if n == 4 else "Trimestre"
        total_dias = (anio.fecha_fin - anio.fecha_inicio).days + 1
        inicio = anio.fecha_inicio
        with transaction.atomic():
            for i in range(n):
                fin = anio.fecha_fin if i == n - 1 else anio.fecha_inicio + timedelta(days=round(total_dias * (i + 1) / n) - 1)
                Periodo.objects.create(anio_lectivo=anio, numero=i + 1, nombre=f"{ROMANOS[i]} {tipo}", fecha_inicio=inicio, fecha_fin=fin)
                inicio = fin + timedelta(days=1)
        messages.success(request, f"Se crearon {n} periodos. Ajusta las fechas si es necesario (vacaciones, etc.).")
    return redirect(reverse("core:anio_detalle", args=[anio.pk]) + "#periodos")


@permiso_requerido("config.colegio")
def periodo_form(request, anio_pk=None, pk=None):
    periodo = get_object_or_404(Periodo, pk=pk) if pk else None
    anio = periodo.anio_lectivo if periodo else get_object_or_404(AnioLectivo, pk=anio_pk)
    inicial = {}
    if not periodo:
        siguiente = (anio.periodos.order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
        inicial = {"numero": siguiente}
    form = PeriodoForm(request.POST or None, instance=periodo, anio_lectivo=anio, initial=inicial)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.anio_lectivo = anio
        p.save()
        messages.success(request, f"Periodo «{p.nombre}» guardado.")
        return redirect(reverse("core:anio_detalle", args=[anio.pk]) + "#periodos")
    return _form(
        request,
        form,
        "Editar periodo" if periodo else "Nuevo periodo",
        reverse("core:anio_detalle", args=[anio.pk]),
        [(f"Año {anio}", reverse("core:anio_detalle", args=[anio.pk]))],
        subtitulo=f"Año lectivo {anio}",
    )


@permiso_requerido("config.colegio")
@require_POST
def periodo_eliminar(request, pk):
    periodo = get_object_or_404(Periodo, pk=pk)
    anio_pk = periodo.anio_lectivo_id
    try:
        periodo.delete()
        messages.success(request, "Periodo eliminado.")
    except ProtectedError:
        messages.error(request, "No se puede eliminar: ya tiene información registrada (notas, etc.).")
    return redirect(reverse("core:anio_detalle", args=[anio_pk]) + "#periodos")


# --- Secciones --------------------------------------------------------------

@permiso_requerido("config.colegio")
def secciones_crear(request, anio_pk):
    anio = get_object_or_404(AnioLectivo, pk=anio_pk)
    form = CrearSeccionesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        creadas = existentes = 0
        with transaction.atomic():
            for grado in form.cleaned_data["grados"]:
                modo = form.cleaned_data["modo_asistencia"]
                if modo == "AUTO":
                    modo = ModoAsistencia.POR_CURSO if grado.nivel.nombre.lower() == "secundaria" else ModoAsistencia.DIARIA
                for nombre in form.cleaned_data["secciones"]:
                    _, nueva = Seccion.objects.get_or_create(
                        anio_lectivo=anio,
                        grado=grado,
                        nombre=nombre,
                        defaults={"turno": form.cleaned_data["turno"], "vacantes": form.cleaned_data["vacantes"],
                                  "modo_asistencia": modo},
                    )
                    creadas += nueva
                    existentes += not nueva
        msg = f"Se crearon {creadas} secciones."
        if existentes:
            msg += f" {existentes} ya existían y no se modificaron."
        messages.success(request, msg)
        return redirect(reverse("core:anio_detalle", args=[anio.pk]) + "#secciones")
    niveles = Nivel.objects.prefetch_related("grados")
    return render(request, "core/config/secciones_crear.html", {"form": form, "anio": anio, "niveles": niveles})


@permiso_requerido("config.colegio")
def seccion_form(request, anio_pk=None, pk=None):
    seccion = get_object_or_404(Seccion, pk=pk) if pk else None
    anio = seccion.anio_lectivo if seccion else get_object_or_404(AnioLectivo, pk=anio_pk)
    form = SeccionForm(request.POST or None, instance=seccion, anio_lectivo=anio)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.anio_lectivo = anio
        s.nombre = s.nombre.strip().upper()
        s.save()
        messages.success(request, f"Sección {s} guardada.")
        return redirect(reverse("core:anio_detalle", args=[anio.pk]) + "#secciones")
    return _form(
        request,
        form,
        f"Editar sección {seccion.grado.nombre} {seccion.nombre}" if seccion else "Nueva sección",
        reverse("core:anio_detalle", args=[anio.pk]),
        [(f"Año {anio}", reverse("core:anio_detalle", args=[anio.pk]))],
        subtitulo=f"Año lectivo {anio}",
    )


@permiso_requerido("config.colegio")
@require_POST
def seccion_eliminar(request, pk):
    seccion = get_object_or_404(Seccion, pk=pk)
    anio_pk = seccion.anio_lectivo_id
    try:
        seccion.delete()
        messages.success(request, "Sección eliminada.")
    except ProtectedError:
        messages.error(request, "No se puede eliminar: la sección ya tiene alumnos u otra información registrada.")
    return redirect(reverse("core:anio_detalle", args=[anio_pk]) + "#secciones")


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

    inactivos = set(ajustes.modulos_inactivos)
    secciones = []
    for mod in ["alumnos", *[m[0] for m in MODULOS], "config"]:
        if mod in inactivos:
            continue  # los módulos que el administrador desactivó no se muestran
        secciones.append({
            "codigo": mod, "nombre": NOMBRE_MODULO[mod], "inactivo": mod in inactivos,
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
        messages.info(request, "Dirección siempre tiene acceso total; no se puede modificar.")
        return redirect("core:roles")

    class RolForm(f.Form):
        nombre = f.CharField(label="Nombre del rol", max_length=60, help_text="Por ejemplo: Secretaría, Auxiliar, Coordinación académica.")
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


# --- Datos del colegio ----------------------------------------------------------

@permiso_requerido("config.colegio")
def datos_colegio(request):
    from .forms import DatosColegioForm
    from .models import Ajustes

    ajustes = Ajustes.cargar()
    logo_antes = ajustes.logo.name if ajustes.logo else ""
    form = DatosColegioForm(request.POST or None, request.FILES or None, instance=ajustes)
    if request.method == "POST" and form.is_valid():
        a = form.save()
        if a.logo and a.logo.name != logo_antes:
            try:
                a.generar_iconos()
            except Exception:  # imagen dañada o formato raro
                a.logo = logo_antes or None
                a.save()
                messages.error(request, "No se pudo procesar el logo. Prueba con otra imagen PNG o JPG.")
                return redirect("core:datos_colegio")
            a.save(update_fields=["version_logo"])
        if not a.logo and a.version_logo:
            a.version_logo = 0
            a.save(update_fields=["version_logo"])
        messages.success(request, "Datos del colegio guardados. Si instalaste la app en el celular, el ícono nuevo puede tardar en aparecer (o reinstálala).")
        return redirect("core:datos_colegio")
    return render(request, "core/config/colegio.html", {"form": form, "c": ajustes})


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
    """El administrador principal (superusuario) decide qué módulos usa el colegio.
    Dirección no puede cambiarlo: solo reparte permisos dentro de los módulos activos."""
    from .models import Ajustes

    ajustes = Ajustes.cargar()
    if request.method == "POST":
        activos = set(request.POST.getlist("modulo"))
        ajustes.modulos_inactivos = [m[0] for m in MODULOS if m[0] not in activos]
        ajustes.save(update_fields=["modulos_inactivos"])
        apagados = [m[1] for m in MODULOS if m[0] in ajustes.modulos_inactivos]
        messages.success(request, "Módulos guardados." + (f" Desactivados: {', '.join(apagados)}." if apagados else " Todos activos."))
        return redirect("core:modulos")
    inactivos = set(ajustes.modulos_inactivos)
    return render(request, "core/config/modulos.html", {
        "modulos": [{"codigo": m[0], "nombre": m[1], "icono": m[2], "texto": m[3], "activo": m[0] not in inactivos} for m in MODULOS],
    })
