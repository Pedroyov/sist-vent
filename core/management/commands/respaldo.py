"""Copia de seguridad: python manage.py respaldo [--carpeta D:\\respaldos] [--guardar 30]

Guarda la base de datos (SQLite, copiada de forma segura aunque el sistema esté en uso) y las fotos
subidas (logo, productos) en un .zip con fecha y hora. Borra los respaldos más viejos y deja los últimos N.
Con PostgreSQL usa pg_dump; si no está instalado (en el hosting), guarda los datos con dumpdata (se restauran con
`migrate` + `loaddata` en una base vacía). Para hacerlo todos los días: respaldo.bat + Programador de tareas de
Windows (ver README), o en el hosting un trabajo programado con `python manage.py respaldo --nube`.

--nube: sube el .zip a DigitalOcean Spaces (carpeta respaldos/ de la empresa, privada) y deja ahí los últimos N.
Las fotos ya están en Spaces en ese caso, así que el .zip lleva solo los datos.
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
        parser.add_argument("--nube", action="store_true", help="Subirlo a DigitalOcean Spaces (necesita SPACES_BUCKET).")

    def handle(self, *args, carpeta, guardar, nube=False, **opciones):
        if nube and not settings.SPACES_BUCKET:
            raise CommandError("Para --nube pon SPACES_BUCKET y sus claves en las variables de entorno.")
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
                except OSError:  # sin pg_dump (hosting): los datos en JSON
                    copia = Path(tmp) / "datos.json"
                    from django.core.management import call_command

                    call_command("dumpdata", natural_foreign=True, output=str(copia), verbosity=0,
                                 exclude=["contenttypes", "auth.permission", "sessions", "admin.logentry"])
                except subprocess.CalledProcessError as e:
                    raise CommandError(f"No se pudo ejecutar pg_dump: {e.stderr.decode(errors='ignore')[:300]}")
            else:
                raise CommandError(f"Base de datos no soportada para respaldo: {motor}")
            with zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(copia, copia.name)
                media = Path(settings.MEDIA_ROOT)
                if not settings.SPACES_BUCKET and media.exists():  # con Spaces las fotos ya están en la nube
                    for f in media.rglob("*"):
                        if f.is_file():
                            z.write(f, Path("media") / f.relative_to(media))
        if nube:
            self._subir(archivo, guardar)
        viejos = sorted(destino.glob("respaldo_*.zip"))[:-guardar] if guardar > 0 else []
        for v in viejos:
            v.unlink()
        mb = archivo.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Respaldo listo: {archivo} ({mb:.1f} MB). Se conservan los últimos {guardar}."))

    def _subir(self, archivo, guardar):
        from django.core.files.storage import default_storage

        try:
            with open(archivo, "rb") as f:
                default_storage.save(f"respaldos/{archivo.name}", f)
            _, nombres = default_storage.listdir("respaldos")
            for viejo in sorted(n for n in nombres if n.startswith("respaldo_"))[:-guardar] if guardar > 0 else []:
                default_storage.delete(f"respaldos/{viejo}")
        except Exception as e:  # noqa: BLE001
            raise CommandError(f"El respaldo se hizo ({archivo}) pero no se pudo subir a Spaces: {e}")
        self.stdout.write(self.style.SUCCESS(f"Subido a Spaces: respaldos/{archivo.name}"))
