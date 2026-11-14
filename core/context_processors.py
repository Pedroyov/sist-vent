from django.conf import settings
from .permisos import PermisosPlantilla
from .roles import roles_de


def colegio(request):
    """Datos disponibles en todas las plantillas."""
    from .models import Ajustes

    datos = Ajustes.cargar()
    contexto = {
        "COLEGIO": datos,
        "COLEGIO_NOMBRE": datos.nombre_mostrar,
        "COLEGIO_NOMBRE_CORTO": datos.corto_mostrar,
        "DEMO": settings.DEMO,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .models import AnioLectivo

        contexto.update(
            {
                "ANIO_ACTUAL": AnioLectivo.actual(),
                "MIS_ROLES": roles_de(user),
                "P": PermisosPlantilla(user),
            }
        )
    return contexto
