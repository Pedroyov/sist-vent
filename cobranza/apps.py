from django.apps import AppConfig


class CobranzaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cobranza"
    verbose_name = "Cobranza"

    def ready(self):
        from . import signals  # noqa: F401
