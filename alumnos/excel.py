"""Plantilla, importación y exportación de alumnos en Excel."""
import re
import unicodedata
from datetime import date, datetime

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.models import Seccion

from .models import Alumno, AlumnoApoderado, Apoderado, Matricula

# (clave interna, encabezado en Excel, obligatorio, ancho)
COLUMNAS = [
    ("dni", "DNI alumno", True, 12),
    ("ap_paterno", "Apellido paterno", True, 18),
    ("ap_materno", "Apellido materno", False, 18),
    ("nombres", "Nombres", True, 22),
    ("fecha_nac", "Fecha nacimiento", False, 15),
    ("sexo", "Sexo (M/F)", False, 10),
    ("nivel", "Nivel", True, 12),
    ("grado", "Grado", True, 10),
    ("seccion", "Sección", True, 9),
    ("dni_apo", "DNI apoderado", False, 14),
    ("ap_apo", "Apellidos apoderado", False, 22),
    ("nom_apo", "Nombres apoderado", False, 20),
    ("parentesco", "Parentesco", False, 12),
    ("celular", "Celular apoderado", False, 14),
    ("correo", "Correo apoderado", False, 24),
    ("direccion", "Dirección", False, 30),
]

PARENTESCOS = {
    "padre": "PADRE", "papa": "PADRE", "papá": "PADRE",
    "madre": "MADRE", "mama": "MADRE", "mamá": "MADRE",
    "abuelo": "ABUELO", "abuela": "ABUELO", "abuelo(a)": "ABUELO",
    "tio": "TIO", "tia": "TIO", "tío": "TIO", "tía": "TIO", "tio(a)": "TIO",
    "hermano": "HERMANO", "hermana": "HERMANO",
    "tutor": "TUTOR", "tutora": "TUTOR", "tutor legal": "TUTOR",
    "otro": "OTRO",
}

AZUL = PatternFill("solid", fgColor="0D6EFD")


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


def _encabezados(ws, fila=1):
    for i, (_, titulo, obligatorio, ancho) in enumerate(COLUMNAS, start=1):
        c = ws.cell(row=fila, column=i, value=titulo + (" *" if obligatorio else ""))
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = AZUL
        c.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = "A2"


def _a_bytes(wb):
    from core.excel import a_bytes

    return a_bytes(wb)


# --- Plantilla --------------------------------------------------------------

def plantilla():
    wb = Workbook()
    ws = wb.active
    ws.title = "Alumnos"
    _encabezados(ws)
    ejemplo = ["71234567", "Quispe", "Mamani", "Ana Lucía", "15/04/2017", "F", "Primaria", "3", "A",
               "41234567", "Mamani Flores", "Rosa", "Madre", "987654321", "rosa@correo.com", "Av. Los Olivos 123"]
    # columnas de texto para no perder los ceros a la izquierda del DNI
    for clave in ("dni", "dni_apo", "celular"):
        col = get_column_letter([c[0] for c in COLUMNAS].index(clave) + 1)
        for fila in range(2, 1002):
            ws[f"{col}{fila}"].number_format = "@"

    dv_nivel = DataValidation(type="list", formula1='"Inicial,Primaria,Secundaria"', allow_blank=False)
    dv_sexo = DataValidation(type="list", formula1='"M,F"', allow_blank=True)
    dv_par = DataValidation(type="list", formula1='"Madre,Padre,Abuelo,Tío,Hermano,Tutor,Otro"', allow_blank=True)
    for dv, clave in ((dv_nivel, "nivel"), (dv_sexo, "sexo"), (dv_par, "parentesco")):
        col = get_column_letter([c[0] for c in COLUMNAS].index(clave) + 1)
        dv.add(f"{col}2:{col}1001")
        ws.add_data_validation(dv)

    ayuda = wb.create_sheet("Instrucciones")
    lineas = [
        "CÓMO LLENAR LA PLANTILLA",
        "",
        "• Una fila por alumno. Las columnas con * son obligatorias.",
        "• Abajo hay una fila de ejemplo de cómo debe quedar cada alumno.",
        "• DNI: 8 dígitos. Si tiene otro documento (carné de extranjería), escríbelo tal cual.",
        "• Fecha de nacimiento: dd/mm/aaaa (por ejemplo 15/04/2017).",
        "• Nivel: Inicial, Primaria o Secundaria.",
        "• Grado: solo el número. Inicial: 3, 4 o 5 (años). Primaria: 1 a 6. Secundaria: 1 a 5.",
        "• Sección: la letra (A, B…). Las secciones deben estar creadas antes en Configuración.",
        "• Apoderado: opcional, pero recomendado para la cobranza. Si dos hermanos tienen",
        "  el mismo DNI de apoderado, se registra una sola vez y queda vinculado a ambos.",
        "• Si el DNI del alumno ya existe en el sistema, se actualizan sus datos y su sección.",
    ]
    for i, t in enumerate(lineas, start=1):
        ayuda.cell(row=i, column=1, value=t).font = Font(bold=(i == 1), size=12 if i == 1 else 11)
    fila = len(lineas) + 2
    ayuda.cell(row=fila, column=1, value="EJEMPLO").font = Font(bold=True)
    for i, (_, titulo, _, _) in enumerate(COLUMNAS, start=1):
        ayuda.cell(row=fila + 1, column=i, value=titulo).font = Font(bold=True)
        ayuda.cell(row=fila + 2, column=i, value=ejemplo[i - 1])
        ayuda.column_dimensions[get_column_letter(i)].width = COLUMNAS[i - 1][3]
    return _a_bytes(wb)


# --- Exportar ---------------------------------------------------------------

def exportar(matriculas_o_alumnos, anio):
    """Recibe alumnos (con .mat del año ya cargada, ver vista) y genera el Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = f"Alumnos {anio}" if anio else "Alumnos"
    _encabezados(ws)
    ws.cell(row=1, column=len(COLUMNAS) + 1, value="Estado").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=1, column=len(COLUMNAS) + 1).fill = AZUL
    for fila, a in enumerate(matriculas_o_alumnos, start=2):
        m = getattr(a, "mat", None)
        apo_rel = a.vinculos.all()
        apo_rel = sorted(apo_rel, key=lambda v: (not v.responsable_pago, v.id))
        v = apo_rel[0] if apo_rel else None
        valores = [
            a.numero_documento, a.apellido_paterno, a.apellido_materno, a.nombres,
            a.fecha_nacimiento.strftime("%d/%m/%Y") if a.fecha_nacimiento else "",
            a.sexo,
            m.seccion.grado.nivel.nombre if m else "",
            m.seccion.grado.nombre if m else "",
            m.seccion.nombre if m else "",
            v.apoderado.numero_documento if v else "",
            v.apoderado.apellidos if v else "",
            v.apoderado.nombres if v else "",
            v.get_parentesco_display() if v else "",
            v.apoderado.celular if v else "",
            v.apoderado.email if v else "",
            a.direccion,
            m.get_estado_display() if m else "Sin matrícula",
        ]
        for col, val in enumerate(valores, start=1):
            ws.cell(row=fila, column=col, value=val)
    ws.column_dimensions[get_column_letter(len(COLUMNAS) + 1)].width = 14
    ws.auto_filter.ref = ws.dimensions
    return _a_bytes(wb)


# --- Importar ---------------------------------------------------------------

def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _documento(v):
    t = _texto(v).replace(" ", "").upper()
    if t.isdigit() and 6 <= len(t) < 8:
        t = t.zfill(8)  # Excel quita los ceros a la izquierda
    return t


def _fecha(v):
    if v in (None, ""):
        return None, None
    if isinstance(v, datetime):
        return v.date(), None
    if isinstance(v, date):
        return v, None
    t = _texto(v)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).date(), None
        except ValueError:
            pass
    return None, f"Fecha de nacimiento no válida: «{t}» (usa dd/mm/aaaa)"


def _mapa_secciones(anio):
    """{(nivel_normalizado, numero_grado, letra): seccion}"""
    mapa = {}
    for s in Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel"):
        num = re.search(r"\d+", s.grado.nombre)
        num = int(num.group()) if num else s.grado.orden
        mapa[(_norm(s.grado.nivel.nombre), num, s.nombre.upper())] = s
    return mapa


def leer(archivo, anio):
    """
    Lee el Excel y valida cada fila sin guardar nada.
    Devuelve (filas, errores_generales). Cada fila: dict con 'n', 'datos', 'errores', 'accion'.
    """
    try:
        wb = load_workbook(archivo, data_only=True, read_only=True)
    except Exception:
        return [], ["No se pudo abrir el archivo. Verifica que sea un Excel (.xlsx) válido."]
    ws = wb["Alumnos"] if "Alumnos" in wb.sheetnames else wb.worksheets[0]
    filas_excel = list(ws.iter_rows(values_only=True))
    if not filas_excel:
        return [], ["El archivo está vacío."]

    # ubicar columnas por encabezado (sin importar el orden)
    encabezados = [_norm(_texto(h).replace("*", "")) for h in filas_excel[0]]
    indices = {}
    for clave, titulo, obligatorio, _ in COLUMNAS:
        t = _norm(titulo)
        if t in encabezados:
            indices[clave] = encabezados.index(t)
        elif obligatorio:
            return [], [f"Falta la columna «{titulo}». Usa la plantilla descargable."]

    secciones = _mapa_secciones(anio)
    existentes = set(Alumno.objects.values_list("numero_documento", flat=True))
    vistos = {}
    filas = []
    for n, valores in enumerate(filas_excel[1:], start=2):
        crudo = {k: (valores[i] if i < len(valores) else None) for k, i in indices.items()}
        if all(_texto(v) == "" for v in crudo.values()):
            continue
        errores = []
        d = {
            "dni": _documento(crudo.get("dni")),
            "ap_paterno": _texto(crudo.get("ap_paterno")).upper(),
            "ap_materno": _texto(crudo.get("ap_materno")).upper(),
            "nombres": _texto(crudo.get("nombres")).upper(),
            "sexo": _texto(crudo.get("sexo")).upper()[:1],
            "nivel": _texto(crudo.get("nivel")),
            "grado": _texto(crudo.get("grado")),
            "seccion": _texto(crudo.get("seccion")).upper(),
            "dni_apo": _documento(crudo.get("dni_apo")),
            "ap_apo": _texto(crudo.get("ap_apo")).upper(),
            "nom_apo": _texto(crudo.get("nom_apo")).upper(),
            "parentesco": _texto(crudo.get("parentesco")),
            "celular": re.sub(r"[^\d+]", "", _texto(crudo.get("celular"))),
            "correo": _texto(crudo.get("correo")).lower(),
            "direccion": _texto(crudo.get("direccion")),
        }
        fecha, err = _fecha(crudo.get("fecha_nac"))
        d["fecha_nac"] = fecha.isoformat() if fecha else ""
        if err:
            errores.append(err)

        if not d["dni"]:
            errores.append("Falta el DNI del alumno.")
        elif d["dni"].isdigit() and len(d["dni"]) != 8:
            errores.append(f"DNI «{d['dni']}» debe tener 8 dígitos.")
        elif d["dni"] in vistos:
            errores.append(f"DNI repetido (también en la fila {vistos[d['dni']]}).")
        else:
            vistos[d["dni"]] = n
        if not d["ap_paterno"]:
            errores.append("Falta el apellido paterno.")
        if not d["nombres"]:
            errores.append("Faltan los nombres.")
        if d["sexo"] and d["sexo"] not in ("M", "F"):
            errores.append("Sexo debe ser M o F.")

        num = re.search(r"\d+", d["grado"])
        clave = (_norm(d["nivel"]), int(num.group()) if num else None, d["seccion"])
        seccion = secciones.get(clave)
        if not (d["nivel"] and num and d["seccion"]):
            errores.append("Falta nivel, grado o sección.")
        elif not seccion:
            errores.append(f"No existe la sección {d['nivel']} {d['grado']} «{d['seccion']}» en {anio}. Créala en Configuración.")
        d["seccion_id"] = seccion.pk if seccion else None
        d["seccion_txt"] = f"{seccion.grado.nombre} {seccion.nombre} · {seccion.grado.nivel}" if seccion else ""

        if d["dni_apo"]:
            if d["dni_apo"].isdigit() and len(d["dni_apo"]) != 8:
                errores.append(f"DNI del apoderado «{d['dni_apo']}» debe tener 8 dígitos.")
            if not (d["ap_apo"] and d["nom_apo"]):
                errores.append("Faltan apellidos o nombres del apoderado.")
            d["parentesco_cod"] = PARENTESCOS.get(_norm(d["parentesco"]), "OTRO" if d["parentesco"] else "MADRE")

        filas.append({
            "n": n,
            "datos": d,
            "errores": errores,
            "accion": "Actualizar" if d["dni"] in existentes else "Nuevo",
        })
    if not filas:
        return [], ["No se encontraron alumnos en el archivo."]
    return filas, []


@transaction.atomic
def importar(filas, anio):
    """Guarda las filas ya validadas. Devuelve un resumen."""
    resumen = {"nuevos": 0, "actualizados": 0, "matriculas": 0, "cambios_seccion": 0, "apoderados": 0}
    for fila in filas:
        d = fila["datos"]
        alumno, creado = Alumno.objects.get_or_create(
            numero_documento=d["dni"],
            defaults={"tipo_documento": "DNI" if d["dni"].isdigit() else "OTRO",
                      "apellido_paterno": d["ap_paterno"], "nombres": d["nombres"]},
        )
        alumno.apellido_paterno = d["ap_paterno"]
        alumno.apellido_materno = d["ap_materno"]
        alumno.nombres = d["nombres"]
        if d["fecha_nac"]:
            alumno.fecha_nacimiento = date.fromisoformat(d["fecha_nac"])
        if d["sexo"]:
            alumno.sexo = d["sexo"]
        if d["direccion"]:
            alumno.direccion = d["direccion"]
        alumno.save()
        resumen["nuevos" if creado else "actualizados"] += 1

        mat = Matricula.objects.filter(alumno=alumno, anio_lectivo=anio).first()
        if mat is None:
            Matricula.objects.create(
                alumno=alumno, anio_lectivo=anio, seccion_id=d["seccion_id"],
                tipo=Matricula.Tipo.NUEVO if creado else Matricula.Tipo.RATIFICACION,
            )
            resumen["matriculas"] += 1
        elif mat.seccion_id != d["seccion_id"]:
            mat.seccion_id = d["seccion_id"]
            mat.save(update_fields=["seccion"])
            resumen["cambios_seccion"] += 1

        if d["dni_apo"]:
            apo, apo_creado = Apoderado.objects.get_or_create(
                numero_documento=d["dni_apo"],
                defaults={"tipo_documento": "DNI" if d["dni_apo"].isdigit() else "OTRO",
                          "apellidos": d["ap_apo"], "nombres": d["nom_apo"]},
            )
            if d["celular"]:
                apo.celular = d["celular"]
            if d["correo"]:
                apo.email = d["correo"]
            if d["direccion"] and not apo.direccion:
                apo.direccion = d["direccion"]
            apo.save()
            resumen["apoderados"] += apo_creado
            _, nuevo_vinculo = AlumnoApoderado.objects.get_or_create(
                alumno=alumno, apoderado=apo,
                defaults={"parentesco": d.get("parentesco_cod", "MADRE"),
                          "responsable_pago": not alumno.vinculos.exists()},
            )
    return resumen
