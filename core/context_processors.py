from django.conf import settings

from .glosario import palabras
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
        "ADMIN_ACTIVO": settings.ADMIN_ACTIVO,
        "T": palabras(datos),
    }
    user = getattr(request, "user", None)
    if settings.DEMO and not (user is not None and user.is_authenticated):
        from .roles import usuarios_demo

        contexto["DEMO_USUARIOS"] = usuarios_demo(datos)
    if user is not None and user.is_authenticated:
        from .ayuda import de as ayuda_de

        contexto.update({"MIS_ROLES": roles_de(user), "P": PermisosPlantilla(user), "AYUDA": ayuda_de(request)})
        from ventas.models import MetodoPago

        from .permisos import puede

        aceptados = datos.metodos_aceptados
        contexto["METODOS_PAGO"] = [(k, v) for k, v in MetodoPago.choices
                                    if k in aceptados and k != MetodoPago.SALDO and (k != MetodoPago.CREDITO or (puede(user, "clientes.fiar") and datos.tiene_modulo("clientes")))]
    return contexto
