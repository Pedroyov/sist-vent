from django.conf import settings

from .permisos import PermisosPlantilla
from .roles import roles_de


def negocio(request):
    """Datos disponibles en todas las plantillas."""
    from .models import Ajustes

    datos = Ajustes.cargar()
    contexto = {
        "NEGOCIO": datos,
        "NEGOCIO_NOMBRE": datos.nombre_mostrar,
        "NEGOCIO_NOMBRE_CORTO": datos.corto_mostrar,
        "DEMO": settings.DEMO,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        contexto.update({"MIS_ROLES": roles_de(user), "P": PermisosPlantilla(user)})
        from ventas.models import MetodoPago

        from .permisos import puede

        aceptados = datos.metodos_aceptados
        contexto["METODOS_PAGO"] = [(k, v) for k, v in MetodoPago.choices
                                    if k in aceptados and (k != MetodoPago.CREDITO or (puede(user, "clientes.fiar") and datos.tiene_modulo("clientes")))]
    return contexto
