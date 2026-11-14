"""Copia de seguridad: python manage.py respaldo [--carpeta D:\\respaldos] [--guardar 30]

Guarda la base de datos (SQLite, copiada de forma segura aunque el sistema esté en uso) y las fotos
subidas (logo, productos) en un .zip con fecha y hora. Borra los respaldos más viejos y deja los últimos N.
Con PostgreSQL usa pg_dump (debe estar instalado). Para hacerlo todos los días: respaldo.bat + Programador
de tareas de Windows (ver README).
"""
import os
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Hace una copia de seguridad de la base de datos y de las fotos subidas."

    def add_arguments(self, parser):
        parser.add_argument("--carpeta", default=str(Path(settings.BASE_DIR) / "respaldos"),
                            help="Dónde guardar (mejor otro disco, una USB o una carpeta sincronizada con la nube).")
        parser.add_argument("--guardar", type=int, default=30, help="Cuántos respaldos conservar (los más viejos se borran).")

    def handle(self, *args, carpeta, guardar, **opciones):
        destino = Path(carpeta)
        destino.mkdir(parents=True, exist_ok=True)
        marca = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        archivo = destino / f"respaldo_{marca}.zip"
        motor = connection.settings_dict["ENGINE"]
        with tempfile.TemporaryDirectory() as tmp:
            if "sqlite" in motor:
                copia = Path(tmp) / "db.sqlite3"
                origen = sqlite3.connect(connection.settings_dict["NAME"])
                dest = sqlite3.connect(copia)
                with dest:
                    origen.backup(dest)  # copia consistente aunque haya ventas en curso
                dest.close()
                origen.close()
            elif "postgresql" in motor:
                copia = Path(tmp) / "db.sql"
                d = connection.settings_dict
                entorno = {**os.environ, "PGPASSWORD": d.get("PASSWORD") or ""}
                cmd = ["pg_dump", "-h", d.get("HOST") or "localhost", "-p", str(d.get("PORT") or 5432), "-U", d.get("USER") or "",
                       "-f", str(copia), d["NAME"]]
                try:
                    subprocess.run(cmd, check=True, env=entorno, capture_output=True)
                except (OSError, subprocess.CalledProcessError) as e:
                    raise CommandError(f"No se pudo ejecutar pg_dump: {e}")
            else:
                raise CommandError(f"Base de datos no soportada para respaldo: {motor}")
            with zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(copia, copia.name)
                media = Path(settings.MEDIA_ROOT)
                if media.exists():
                    for f in media.rglob("*"):
                        if f.is_file():
                            z.write(f, Path("media") / f.relative_to(media))
        viejos = sorted(destino.glob("respaldo_*.zip"))[:-guardar] if guardar > 0 else []
        for v in viejos:
            v.unlink()
        mb = archivo.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Respaldo listo: {archivo} ({mb:.1f} MB). Se conservan los últimos {guardar}."))
