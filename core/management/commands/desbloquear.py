"""Soporte: dejar entrar a quien se bloqueó por intentos fallidos, sin esperar los 15 minutos.

    python manage.py desbloquear rosa        # el usuario rosa (y la conexión desde donde se equivocó)
    python manage.py desbloquear --todos     # todos los bloqueos (por ejemplo, todo el local quedó bloqueado)
"""
from django.core.management.base import BaseCommand, CommandError

from core.bitacora import anotar
from core.forms import cache_seguridad, desbloquear


class Command(BaseCommand):
    help = "Soporte: quita el bloqueo por intentos fallidos de un usuario o de todos."

    def add_arguments(self, parser):
        parser.add_argument("usuario", nargs="?", help="Nombre de usuario (como entra al sistema).")
        parser.add_argument("--todos", action="store_true", help="Quita todos los bloqueos de ingreso.")

    def handle(self, usuario=None, todos=False, **opciones):
        if todos:
            cache_seguridad().clear()
            anotar("ingreso.desbloqueado", "Soporte quitó todos los bloqueos de ingreso")
            self.stdout.write(self.style.SUCCESS("Listo: se quitaron todos los bloqueos."))
            return
        if not usuario:
            raise CommandError("Indica el usuario o usa --todos.")
        desbloquear(usuario.strip())
        anotar("ingreso.desbloqueado", f"Soporte desbloqueó el ingreso de «{usuario.strip()}»")
        self.stdout.write(self.style.SUCCESS(f"Listo: {usuario.strip()} ya puede volver a entrar."))
