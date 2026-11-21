from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        def ingreso(sender, request, user, **kwargs):
            """Cada ingreso de quien puede todo (Administración o superusuario) queda en la bitácora."""
            from .bitacora import anotar
            from .permisos import acceso_total

            if acceso_total(user):
                from .bitacora import equipo

                agente = request.META.get("HTTP_USER_AGENT", "") if request else ""
                anotar("ingreso", f"Ingresó {user.get_full_name() or user.username}" + (f" desde {equipo(agente)}" if agente else ""),
                       usuario=user, despues={"navegador": agente[:250]} if agente else None)

        user_logged_in.connect(ingreso, dispatch_uid="bitacora_ingreso")
