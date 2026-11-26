"""Deja lista una instalación nueva para una empresa: python manage.py crear_empresa --nombre "Bodega Doña Rosa" \\
       --rubro TIE --usuario rosa --segundo-paso correo [--ruc 10456789012] [--nombre-admin "Rosa Mamani"] [--correo rosa@ejemplo.com]

--segundo-paso se pregunta siempre (se decide con el cliente): «no» (solo la contraseña), «correo» (código al correo al
entrar desde un equipo nuevo; necesita --correo) o «app» (Google o Microsoft Authenticator). Se puede cambiar después en
Datos del negocio.

Se corre una sola vez, en la base vacía de la empresa (después de `migrate`): pone los datos del negocio, enciende los
módulos y funciones de su tipo de negocio y crea al administrador principal con una clave temporal que se muestra una
sola vez. Si la base ya tiene usuarios, no hace nada (para no pisar una empresa que ya trabaja).
"""
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Ajustes, Rubro


class Command(BaseCommand):
    help = "Prepara una instalación nueva: datos del negocio, módulos según el rubro y el administrador principal."

    def add_arguments(self, parser):
        parser.add_argument("--nombre", required=True, help="Nombre comercial.")
        parser.add_argument("--rubro", required=True, choices=Rubro.values, help="TIE, RES, ROP, LIB, PEL, ACA u OTR.")
        parser.add_argument("--usuario", required=True, help="Usuario del administrador principal.")
        parser.add_argument("--nombre-admin", default="", help="Nombre y apellido del administrador.")
        parser.add_argument("--correo", default="")
        parser.add_argument("--ruc", default="")
        parser.add_argument("--segundo-paso", required=True, choices=["no", "correo", "app"],
                            help="Segundo paso para entrar a Administración: no, correo o app (se decide con el cliente).")

    def handle(self, *args, nombre, rubro, usuario, nombre_admin, correo, ruc, segundo_paso, **opciones):
        from core.permisos import MODULOS, NOMBRE_MODULO
        from core.rubros import aplicar

        User = get_user_model()
        if User.objects.exists():
            raise CommandError("Esta base ya tiene usuarios: crear_empresa es solo para una instalación nueva.")
        nombre = " ".join(nombre.split())[:150]
        ruc = "".join(c for c in ruc if c.isdigit())
        if ruc and len(ruc) != 11:
            raise CommandError("El RUC tiene 11 dígitos.")
        usuario = usuario.strip()
        if not usuario or " " in usuario:
            raise CommandError("El usuario no puede estar vacío ni tener espacios.")
        if segundo_paso == "correo" and "@" not in correo:
            raise CommandError("Con el código por correo, pon el correo del administrador: --correo rosa@ejemplo.com")
        clave = secrets.token_urlsafe(12)
        with transaction.atomic():
            a = Ajustes.cargar()
            a.nombre, a.nombre_corto, a.rubro = nombre, nombre[:30], rubro
            a.codigo_ingreso = {"no": "", "correo": Ajustes.SegundoPaso.CORREO, "app": Ajustes.SegundoPaso.APP}[segundo_paso]
            if ruc:
                a.ruc = ruc
            a.save()
            aplicar(a, modulos=True, forzar=True)  # instalación nueva: exactamente lo del tipo de negocio
            partes = " ".join(nombre_admin.split()).split(" ", 1)
            User.objects.create_superuser(usuario, email=correo.strip(), password=clave, first_name=partes[0][:150],
                                          last_name=(partes[1] if len(partes) > 1 else "")[:150])
        a.refresh_from_db()
        activos = [NOMBRE_MODULO[m[0]] for m in MODULOS if m[0] not in (a.modulos_inactivos or [])]
        self.stdout.write(self.style.SUCCESS(f"Empresa lista: {nombre} ({a.get_rubro_display()})."))
        self.stdout.write(f"Módulos: {', '.join(activos)}.")
        self.stdout.write(f"Administrador principal: {usuario}  ·  clave temporal: {clave}")
        self.stdout.write(f"Segundo paso: {a.get_codigo_ingreso_display()}.")
        self.stdout.write("Esta clave se muestra una sola vez: entrégala al cliente y pídele que la cambie al entrar "
                          "(menú del usuario → Cambiar contraseña; las de Administración, de 10 caracteres o más).")
        if segundo_paso == "app":
            self.stdout.write("Al entrar se le pedirá activar la app de códigos: hazlo con él y guarden los códigos de respaldo.")
        elif not correo:
            self.stdout.write(self.style.WARNING("Sin correo no le llegarán los avisos de ingreso desde un equipo nuevo."))
