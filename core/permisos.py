"""
Módulos y permisos del sistema.

- Cada rol (grupo de Django) tiene una lista de permisos que se marca en
  Configuración → Roles y permisos.
- Dirección y el superusuario siempre tienen todos los permisos (así nadie
  puede quedarse sin acceso a la configuración).
- Un módulo desactivado desaparece para todos, aunque el rol tenga el permiso.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

DIRECCION = "Dirección"
TESORERIA = "Tesorería"
DOCENTE = "Docente"
ROLES_BASE = [DIRECCION, TESORERIA, DOCENTE]

# Módulos que se pueden desactivar. Alumnos y Configuración son la base y siempre están activos.
MODULOS = [
    ("cobranza", "Cobranza", "bi-cash-coin", "Pensiones, pagos, recibos, morosos y otros cobros."),
    ("asistencia", "Asistencia", "bi-calendar-check", "Asistencia diaria o por curso, reportes y avisos."),
    ("notas", "Notas", "bi-journal-check", "Registro de notas, conducta, libretas y SIAGIE."),
    ("programacion", "Programación del año", "bi-calendar2-week",
     "Calendario, plan de estudios, docentes por curso y horarios. Notas y asistencia por curso la usan."),
    ("personal", "Personal", "bi-person-vcard", "Trabajadores, horarios y planilla."),
]
MODULOS_BASE = ("alumnos", "config")

# (código, módulo, descripción, roles que lo tienen por defecto)
PERMISOS = [
    ("alumnos.ver", "alumnos", "Ver alumnos, su ficha y exportar la lista", [TESORERIA]),
    ("alumnos.editar", "alumnos", "Registrar y editar alumnos, apoderados y matrículas; importar Excel", [TESORERIA]),
    ("alumnos.pase", "alumnos", "Pase de año", []),

    ("cobranza.ver", "cobranza", "Ver estados de cuenta, pagos, morosos y reportes de caja", [TESORERIA]),
    ("cobranza.cobrar", "cobranza", "Registrar pagos (por alumno y cobro rápido)", [TESORERIA]),
    ("cobranza.descuentos", "cobranza", "Dar y quitar descuentos", [TESORERIA]),
    ("cobranza.otros", "cobranza", "Crear otros cobros y asignarlos a alumnos", [TESORERIA]),
    ("cobranza.anular", "cobranza", "Anular pagos y eliminar otros cobros", []),
    ("cobranza.configurar", "cobranza", "Montos de matrícula y pensión, cronograma y mora", []),

    ("asistencia.tomar", "asistencia", "Tomar asistencia de sus secciones y cursos (últimos 7 días)", [DOCENTE]),
    ("asistencia.todas", "asistencia", "Tomar y corregir la asistencia de todas las secciones, cualquier fecha", []),
    ("asistencia.reportes", "asistencia", "Resumen del día, reportes de todas las secciones y avisos a padres", []),

    ("notas.registrar", "notas", "Registrar notas de sus cursos y conducta de su tutoría", [DOCENTE]),
    ("notas.todas", "notas", "Ver y editar notas de todas las secciones, incluso con el periodo cerrado", []),
    ("notas.libretas", "notas", "Ver e imprimir libretas de cualquier alumno (el tutor siempre ve las suyas)", [TESORERIA]),
    ("notas.avance", "notas", "Ver el avance del registro de notas por docente", []),
    ("notas.configurar", "notas", "Escala de calificación, competencias y cierre de periodos", []),
    ("notas.siagie", "notas", "Exportar para el SIAGIE y llenar plantillas", []),

    ("programacion.horarios", "programacion", "Ver los horarios de todas las secciones y docentes (su propio horario siempre lo ve)", []),
    ("programacion.editar", "programacion", "Calendario, plan de estudios, cursos, docentes, jornada, horarios y carga docente", []),

    ("personal.ver", "personal", "Ver trabajadores y sus horarios", []),
    ("personal.editar", "personal", "Registrar y editar trabajadores", []),
    ("personal.planilla", "personal", "Ver la planilla y lo que se paga a cada trabajador", []),

    ("config.colegio", "config", "Años lectivos, periodos y secciones", []),
    ("config.usuarios", "config", "Crear y editar usuarios (el rol Dirección solo lo da Dirección)", []),
]
CODIGOS = [p[0] for p in PERMISOS]
MODULO_DE = {p[0]: p[1] for p in PERMISOS}
NOMBRE_MODULO = {"alumnos": "Alumnos", "config": "Configuración", **{m[0]: m[1] for m in MODULOS}}


def permisos_por_defecto(rol):
    if rol == DIRECCION:
        return list(CODIGOS)
    return [p[0] for p in PERMISOS if rol in p[3]]


def modulos_activos():
    from .models import Ajustes

    inactivos = set(Ajustes.cargar().modulos_inactivos)
    return {m[0] for m in MODULOS if m[0] not in inactivos} | set(MODULOS_BASE)


def permisos_de(user):
    """Conjunto de permisos efectivos del usuario (se calcula una vez por petición)."""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    cache = getattr(user, "_sis_permisos", None)
    if cache is not None:
        return cache
    from .models import PermisosRol

    activos = modulos_activos()
    grupos = list(user.groups.values_list("pk", "name"))
    if user.is_superuser or any(nombre == DIRECCION for _, nombre in grupos):
        codigos = set(CODIGOS)
    else:
        codigos = set()
        for lista in PermisosRol.objects.filter(grupo_id__in=[g for g, _ in grupos]).values_list("permisos", flat=True):
            codigos.update(lista or [])
    resultado = frozenset(c for c in codigos if MODULO_DE.get(c) in activos)
    user._sis_permisos = resultado
    user._sis_modulos = activos
    return resultado


def acceso_total(user):
    """Dirección o administrador: tiene todo y es quien maneja roles, permisos y módulos."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name=DIRECCION).exists()


def acceso_total_requerido(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not acceso_total(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return envoltura


def puede(user, *codigos):
    """True si el usuario tiene al menos uno de los permisos."""
    p = permisos_de(user)
    return any(c in p for c in codigos)


def modulo_activo(user, modulo):
    permisos_de(user)
    return modulo in getattr(user, "_sis_modulos", modulos_activos())


def requiere_modulo(modulo):
    """Para vistas propias de docentes (sin permiso fijo): solo exige que el módulo esté activo."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if modulo not in modulos_activos():
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador


def permiso_requerido(*codigos):
    """@permiso_requerido("cobranza.cobrar") — basta con tener uno de los permisos indicados."""
    for c in codigos:
        assert c in CODIGOS, f"Permiso desconocido: {c}"

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not puede(request.user, *codigos):
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        envoltura.permisos = codigos
        return envoltura

    return decorador


class PermisosPlantilla(dict):
    """En plantillas: {% if P.cobranza_ver %} … {% if P.mod_notas %}"""

    def __init__(self, user):
        super().__init__()
        self.user = user

    def __missing__(self, clave):
        if clave == "acceso_total":
            return acceso_total(self.user)
        if clave.startswith("mod_"):
            return modulo_activo(self.user, clave[4:])
        return puede(self.user, clave.replace("_", ".", 1))

    def __contains__(self, clave):
        return True
