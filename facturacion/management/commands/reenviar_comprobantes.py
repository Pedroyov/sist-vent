"""Reenvía a SUNAT (vía el proveedor) los comprobantes pendientes: python manage.py reenviar_comprobantes [--limite 100]

Pensado para una tarea programada (en DigitalOcean App Platform: un «scheduled job» cada 15 minutos; en Windows:
el Programador de tareas). Avisa los que están por vencer el plazo de SUNAT.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from facturacion.servicios import atrasados, reenviar_pendientes, vence_envio


class Command(BaseCommand):
    help = "Reenvía los comprobantes electrónicos pendientes y avisa los que están por vencer el plazo de SUNAT."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=100)

    def handle(self, *args, limite, **opciones):
        ok, mal = reenviar_pendientes(limite=limite)
        self.stdout.write(f"Reenviados: {ok}. Sin respuesta: {mal}.")
        hoy = timezone.localdate()
        urgentes = [c for c in atrasados() if vence_envio(c) <= hoy + timedelta(days=1)]
        for c in urgentes:
            self.stderr.write(f"URGENTE: {c.numero_str} vence el {vence_envio(c):%d/%m/%Y} y sigue sin aceptar ({c.mensaje}).")
        if mal or urgentes:
            raise SystemExit(1)  # la tarea programada lo marca como fallida: alguien debe revisarlo
