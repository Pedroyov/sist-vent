"""Genera el Manual de usuario que se lee dentro del sistema (Ayuda → Manual de usuario), a partir del mismo .md de la
carpeta de documentación. Se corre al cerrar cada lote de cambios, junto con el Word:

    python manage.py generar_manual "C:\\proyectos\\docs\\Manual de usuario – Sistema de ventas.md"

Necesita pandoc (el mismo que genera el .docx). Deja:
- core/manual/manual.html: el contenido, con un id por sección («s-6-3» para la 6.3) para que el «?» abra justo ahí.
- core/manual/indice.json: el índice (capítulos y secciones) y la fecha del manual.
- static/manual/capturas/*.jpg: las capturas en tamaño liviano (cargan rápido con datos móviles).
- static/manual/manual.pdf: el PDF para descargar, si está instalado weasyprint (si no, se deja el que había).
"""
import html
import json
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

ANCHO_CAPTURA = 760


def id_seccion(numero):
    """«6.3» -> «s-6-3»; «6.» o «6» -> «s-6». El «?» de cada pantalla arma el mismo id con su sección."""
    return "s-" + numero.strip(".").replace(".", "-")


class Command(BaseCommand):
    help = "Genera el manual de usuario que se ve dentro del sistema (HTML, índice, capturas livianas y PDF)."

    def add_arguments(self, parser):
        parser.add_argument("md", help="Ruta del Manual de usuario en Markdown (el original de la carpeta de documentación).")

    def handle(self, md, **opciones):
        origen = Path(md)
        if not origen.exists():
            raise CommandError(f"No existe {origen}.")
        base = Path(settings.BASE_DIR)
        destino, estaticos = base / "core" / "manual", base / "static" / "manual"
        (estaticos / "capturas").mkdir(parents=True, exist_ok=True)
        destino.mkdir(parents=True, exist_ok=True)
        texto = origen.read_text(encoding="utf-8")
        fecha = (re.search(r'^date:\s*"?([^"\n]+)"?', texto, re.M) or [None, ""])[1]
        try:
            cuerpo = subprocess.run(["pandoc", "-f", "markdown", "-t", "html5", "--section-divs"], input=texto, capture_output=True,
                                    text=True, check=True, encoding="utf-8").stdout
        except (OSError, subprocess.CalledProcessError) as e:
            raise CommandError(f"No se pudo correr pandoc: {e}")
        indice = []

        def seccion(m):
            nivel, titulo = m.group(2), m.group(4)
            num = re.match(r"(\d+(?:\.\d+)*)\.?\s", html.unescape(re.sub(r"<[^>]+>", "", titulo)) + " ")
            ident = id_seccion(num.group(1)) if num else m.group(1)
            if nivel in ("1", "2"):
                indice.append({"id": ident, "nivel": int(nivel), "texto": html.unescape(re.sub(r"<[^>]+>", "", titulo)).strip()})
            return f'<section id="{ident}" class="level{nivel}">{m.group(3)}<h{nivel}>{titulo}</h{nivel}>'

        cuerpo = re.sub(r'<section id="([^"]*)" class="level(\d)">(\s*)<h\d[^>]*>(.*?)</h\d>', seccion, cuerpo, flags=re.S)
        # capturas: livianas, desde static; sin el ancho fijo del Word
        usadas = set(re.findall(r'src="capturas/([^"]+)"', cuerpo))
        for nombre in sorted(usadas):
            self._captura(origen.parent / "capturas" / nombre, estaticos / "capturas" / (Path(nombre).stem + ".jpg"))
        cuerpo = re.sub(r'src="capturas/([^"]+?)\.\w+"', lambda m: f'src="{settings.STATIC_URL}manual/capturas/{m.group(1)}.jpg" loading="lazy"', cuerpo)
        cuerpo = re.sub(r'\s(?:style="width:[^"]*"|width="[^"]*")', "", cuerpo)
        cuerpo = cuerpo.replace("<table>", '<div class="table-responsive"><table class="table table-sm table-bordered">').replace("</table>", "</table></div>")
        (destino / "manual.html").write_text(cuerpo, encoding="utf-8")
        (destino / "indice.json").write_text(json.dumps({"fecha": fecha, "indice": indice}, ensure_ascii=False, indent=0), encoding="utf-8")
        self.stdout.write(f"Manual: {len(indice)} secciones, {len(usadas)} capturas.")
        self._pdf(cuerpo, fecha, estaticos / "manual.pdf", base)

    def _captura(self, origen, destino):
        from PIL import Image

        if not origen.exists():
            self.stderr.write(f"Falta la captura {origen.name}")
            return
        if destino.exists() and destino.stat().st_mtime >= origen.stat().st_mtime:
            return
        with Image.open(origen) as im:
            im = im.convert("RGB")
            if im.width > ANCHO_CAPTURA:
                im = im.resize((ANCHO_CAPTURA, round(im.height * ANCHO_CAPTURA / im.width)))
            im.save(destino, "JPEG", quality=78, optimize=True)

    def _pdf(self, cuerpo, fecha, destino, base):
        try:
            from weasyprint import HTML
        except ImportError:
            self.stdout.write("PDF: weasyprint no está instalado; se deja el PDF anterior.")
            return
        estilos = """@page { size: A4; margin: 16mm 14mm; } body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.4; }
            h1 { page-break-before: always; font-size: 18pt; } h2 { font-size: 13pt; margin-top: 1.2em; }
            img { max-width: 7cm; max-height: 13cm; display: block; margin: .5em auto; } figure { margin: 0; text-align: center; }
            figcaption { font-size: 9pt; color: #555; } table { border-collapse: collapse; width: 100%; font-size: 9pt; }
            td, th { border: 1px solid #bbb; padding: 3px 5px; vertical-align: top; } code { font-size: 9pt; }"""
        portada = f"<div style='text-align:center;margin-top:8cm'><h1 style='page-break-before:avoid'>Manual de usuario</h1><p>Sistema de ventas</p><p>{html.escape(fecha)}</p></div>"
        cuerpo = cuerpo.replace(f'src="{settings.STATIC_URL}', f'src="{(base / "static").as_uri()}/')
        HTML(string=f"<html><head><meta charset='utf-8'><style>{estilos}</style></head><body>{portada}{cuerpo}</body></html>").write_pdf(destino)
        self.stdout.write(f"PDF: {destino.stat().st_size // 1024} KB.")
