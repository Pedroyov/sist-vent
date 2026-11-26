"""Soporte: quitar el código del celular a un usuario que perdió el celular y los códigos de respaldo (por ejemplo, el
único administrador del negocio). Se corre en la consola del servidor de esa empresa; queda en la bitácora.

    python manage.py quitar_codigo --listar          # quiénes tienen el código activo
    python manage.py quitar_codigo rosa              # se lo quita a «rosa»
    python manage.py quitar_codigo rosa --nota "llamó el 26/11, se verificó su DNI"
    python manage.py quitar_codigo --apagar          # el negocio deja de pedir el segundo paso (correo o app)

Antes de correrlo, verifica que quien llama es de verdad esa persona (por ejemplo, llamándola tú al número del contrato).
Si además olvidó su contraseña: python manage.py changepassword rosa
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core import dos_factor
from core.models import SegundoFactor


class Command(BaseCommand):
    help = "Soporte: quita el código del celular a un usuario (perdió el celular y los códigos de respaldo)."

    def add_arguments(self, parser):
        parser.add_argument("usuario", nargs="?", help="Nombre de usuario (como entra al sistema).")
        parser.add_argument("--listar", action="store_true", help="Muestra quiénes tienen el código del celular activo.")
        parser.add_argument("--nota", default="", help="Por qué se quitó (queda en la bitácora).")
        parser.add_argument("--apagar", action="store_true",
                            help="Quita el segundo paso del negocio (Datos del negocio → Segundo paso: «No pedir»), por ejemplo si el correo no funciona.")

    def handle(self, usuario=None, listar=False, nota="", apagar=False, **opciones):
        if apagar:
            from core.bitacora import anotar
            from core.models import Ajustes

            Ajustes.objects.filter(pk=Ajustes.cargar().pk).update(codigo_ingreso="")
            anotar("config.negocio", "Soporte quitó el segundo paso para entrar a Administración" + (f" ({nota.strip()})" if nota.strip() else ""))
            self.stdout.write(self.style.SUCCESS("Listo: Administración entra solo con su contraseña."))
            if not usuario and not listar:
                return
        if listar or not usuario:
            activos = SegundoFactor.objects.filter(activo=True).select_related("usuario").order_by("usuario__username")
            if not activos:
                self.stdout.write("Nadie tiene el código del celular activo.")
            for f in activos:
                u = f.usuario
                self.stdout.write(f"{u.username:20} {u.get_full_name() or '':30} {'(administrador principal)' if u.is_superuser else ''}")
            if not usuario:
                return
        u = get_user_model().objects.filter(username__iexact=usuario.strip()).first()
        if u is None:
            raise CommandError(f"No existe el usuario «{usuario}». Usa --listar para ver los usuarios con código.")
        if dos_factor.quitar(u, nota=("soporte: " + nota.strip()) if nota.strip() else "soporte"):
            self.stdout.write(self.style.SUCCESS(f"Listo: {u.username} entra con su contraseña y vuelve a activar el código."))
        else:
            self.stdout.write(f"{u.username} no tenía el código del celular activo.")
