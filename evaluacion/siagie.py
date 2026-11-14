"""
Llenado de la plantilla Excel que se descarga del SIAGIE.

No depende de un diseño fijo: en cada hoja busca la columna de DNI/código y la de nombres de
los estudiantes, las columnas de calificación y de conclusión descriptiva, y reconoce el curso
por el nombre de la hoja o los títulos. El usuario revisa y corrige esa detección antes de llenar.
Solo se escriben valores en las celdas de calificación/conclusión; el resto del archivo no se toca.
"""
import re
import unicodedata
from io import BytesIO

from core.excel import como_texto
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from academico.models import Asignacion

from . import servicios as sv
from .models import Comentario, ConfigEvaluacion, Nota

MAX_FILAS, MAX_COLS = 400, 80
NO_NOTA = {"n", "no", "nro", "num", "numero", "orden", "dni", "codigo", "cod", "apellido", "apellidos", "nombre",
           "nombres", "sexo", "fecha", "estudiante", "estudiantes", "alumno", "alumnos", "documento", "situacion",
           "estado", "edad", "tipo"}
CONCLUSION = ("conclus", "descrip", "comentario", "observ")


def norm(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _tokens(texto):
    return {w for w in norm(texto).split() if len(w) > 2}


def _texto_celda(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _doc(v):
    t = re.sub(r"\D", "", _texto_celda(v))
    return t if len(t) in (8, 14) or (6 <= len(t) <= 9) else ""


class Contexto:
    """Datos del sistema para comparar con la plantilla."""

    def __init__(self, seccion, periodo):
        self.seccion, self.periodo = seccion, periodo
        self.alumnos = sv.alumnos_periodo(seccion, periodo)
        self.por_doc, self.por_nombre = {}, {}
        for a in self.alumnos:
            self.por_doc[a.numero_documento.zfill(8) if a.numero_documento.isdigit() else a.numero_documento] = a
            if a.codigo:
                self.por_doc[re.sub(r"\D", "", a.codigo)] = a
            self.por_nombre[frozenset(_tokens(f"{a.apellidos} {a.nombres}"))] = (a, _tokens(a.nombres))
        self.config = ConfigEvaluacion.de(seccion.anio_lectivo, seccion.grado.nivel)
        self.asignaciones = list(Asignacion.objects.filter(seccion=seccion, curso__activo=True).select_related("curso"))
        self.comps = {a.pk: sv.competencias_de(a, self.config) for a in self.asignaciones}

    def alumno_por_doc(self, v):
        d = _doc(v)
        if not d:
            return None
        return self.por_doc.get(d) or self.por_doc.get(d.zfill(8))

    def alumno_por_nombre(self, v):
        toks = _tokens(v)
        if len(toks) < 2:
            return None
        mejor, puntaje, empate = None, 0, False
        for clave, (a, nombres) in self.por_nombre.items():
            comun = len(toks & clave)
            # debe coincidir al menos un nombre de pila y casi todo el texto en ambos sentidos
            if comun < 2 or not (toks & nombres):
                continue
            if comun / len(clave) < 0.75 or comun / len(toks) < 0.75:
                continue
            if comun > puntaje:
                mejor, puntaje, empate = a, comun, False
            elif comun == puntaje:
                empate = True
        return None if empate else mejor

    def curso_de(self, texto):
        t = norm(texto)
        mejor, largo = None, 0
        for a in self.asignaciones:
            nombre = norm(a.curso.nombre)
            abrev = norm(a.curso.abreviatura)
            if nombre and nombre in t and len(nombre) > largo:
                mejor, largo = a, len(nombre)
            elif abrev and len(abrev) >= 2 and re.search(rf"\b{re.escape(abrev)}\b", t) and len(abrev) > largo:
                mejor, largo = a, len(abrev)
        if mejor is None:  # coincidencia por palabras (p. ej. "CIENCIA Y TECNOLOGIA" con tildes o abreviado)
            toks = _tokens(texto)
            for a in self.asignaciones:
                ct = _tokens(a.curso.nombre)
                if ct and len(ct & toks) / len(ct) >= 0.67 and len(ct) > largo:
                    mejor, largo = a, len(ct)
        return mejor


def _valores_hoja(ws):
    """Matriz {(fila, col): texto} con las celdas combinadas resueltas a su valor."""
    celdas = {}
    for fila in ws.iter_rows(min_row=1, max_row=min(ws.max_row, MAX_FILAS), max_col=min(ws.max_column, MAX_COLS)):
        for c in fila:
            if c.value is not None and not isinstance(c, MergedCell):
                celdas[(c.row, c.column)] = _texto_celda(c.value)
    for rango in ws.merged_cells.ranges:
        v = celdas.get((rango.min_row, rango.min_col))
        if v:
            for r in range(rango.min_row, min(rango.max_row, MAX_FILAS) + 1):
                for col in range(rango.min_col, min(rango.max_col, MAX_COLS) + 1):
                    celdas.setdefault((r, col), v)
    return celdas


def _analizar_hoja(ws, ctx):
    celdas = _valores_hoja(ws)
    if not celdas:
        return None
    # 1) Filas de estudiantes: por DNI/código o, si no hay, por nombre
    filas, cols_doc, cols_nombre = {}, {}, {}
    for (r, c), v in celdas.items():
        a = ctx.alumno_por_doc(v)
        if a:
            filas.setdefault(r, a)
            cols_doc[c] = cols_doc.get(c, 0) + 1
    col_doc = max(cols_doc, key=cols_doc.get) if cols_doc else None
    # filas con un documento que no es de ningún alumno de la sección: no adivinar por el nombre
    con_doc_ajeno = {r for (r, c), v in celdas.items() if c == col_doc and _doc(v) and r not in filas}
    por_nombre = {}
    for (r, c), v in celdas.items():
        if r in filas or r in con_doc_ajeno or not re.search(r"[a-zA-Z]{2}", v):
            continue
        a = ctx.alumno_por_nombre(v)
        if a:
            cols_nombre[c] = cols_nombre.get(c, 0) + 1
            por_nombre[r] = a
    # un mismo alumno no puede ocupar dos filas: si pasa, no se llena ninguna de esas filas por nombre
    usados = {a.pk for a in filas.values()}
    conteo = {}
    for a in por_nombre.values():
        conteo[a.pk] = conteo.get(a.pk, 0) + 1
    for r, a in por_nombre.items():
        if a.pk not in usados and conteo[a.pk] == 1:
            filas[r] = a
    if not filas:
        return None
    # columna de nombres también en las filas reconocidas por documento
    for r, a in filas.items():
        ap = norm(a.apellido_paterno)
        for (rr, c), v in celdas.items():
            if rr == r and c != col_doc and ap and ap in norm(v):
                cols_nombre[c] = cols_nombre.get(c, 0) + 1
    col_nombre = max(cols_nombre, key=cols_nombre.get) if cols_nombre else None
    col_ref = max(x for x in (col_doc, col_nombre) if x)

    def parece_estudiante(r):
        if col_doc and _doc(celdas.get((r, col_doc), "")):
            return True
        texto = norm(celdas.get((r, col_nombre), "")) if col_nombre else ""
        return len(texto.split()) >= 2 and texto.split()[0] not in NO_NOTA and not any(k in texto for k in ("apellido", "nombre", "estudiante"))

    primera = min(filas)
    while primera > 1 and parece_estudiante(primera - 1):  # alumnos de la plantilla que no están en el sistema
        primera -= 1
    ultima = max(filas)
    # filas entre la primera y la última que parecen estudiantes pero no se reconocieron
    no_encontrados = []
    for r in range(primera, ultima + 1):
        if r in filas:
            continue
        doc = celdas.get((r, col_doc), "") if col_doc else ""
        nom = celdas.get((r, col_nombre), "") if col_nombre else ""
        if _doc(doc) or re.search(r"[a-zA-Z]{3}", nom):
            no_encontrados.append(f"{doc} {nom}".strip())

    # 2) Encabezados: hasta 6 filas encima de la primera fila de estudiantes
    max_col = max(c for (_, c) in celdas)
    columnas = []
    for c in range(col_ref + 1, max_col + 1):
        partes = []
        for r in range(max(1, primera - 6), primera):
            v = celdas.get((r, c))
            if v and v not in partes:
                partes.append(v)
        titulo = " / ".join(partes[-3:])
        nt = norm(titulo)
        ultima_parte = norm(partes[-1]) if partes else ""
        if ultima_parte.split(" ")[0] in NO_NOTA and not re.search(r"\bc\s*\d", ultima_parte):
            continue
        cerca = [celdas.get((r, c)) for r in (primera - 1, primera - 2) if r >= 1]
        if not any(cerca):
            titulo = ""  # lo de más arriba es un título general, no el de esta columna
        if not titulo:
            # sin título: solo si hay calificaciones escritas en esas filas
            datos = [celdas.get((r, c), "") for r in filas]
            if not any(re.fullmatch(r"(AD|A|B|C|\d{1,2})", d.upper()) for d in datos if d):
                continue
        tipo = "conclusion" if any(x in nt for x in CONCLUSION) else "nota"
        columnas.append({"col": c, "titulo": titulo or f"Columna {c}", "tipo": tipo})
    if not columnas:
        return None

    # 3) Curso de la hoja
    texto_titulos = " ".join([ws.title] + [v for (r, c), v in celdas.items() if r < primera])
    asig = ctx.curso_de(ws.title) or ctx.curso_de(texto_titulos)
    hoja = {
        "nombre": ws.title, "asignacion": asig.pk if asig else None,
        "filas": sorted((r, a.pk) for r, a in filas.items()), "no_encontrados": no_encontrados[:30],
        "columnas": columnas, "col_doc": col_doc, "col_nombre": col_nombre,
    }
    mapear_columnas(hoja, ctx)
    return hoja


def mapear_columnas(hoja, ctx):
    """Asigna cada columna de nota a una competencia y cada columna de conclusión a su nota."""
    comps = ctx.comps.get(hoja["asignacion"]) or []
    notas = [c for c in hoja["columnas"] if c["tipo"] == "nota"]
    usadas = set()
    for col in notas:
        col["competencia"] = None
        t = norm(col["titulo"])
        m = re.search(r"\b(?:c|comp|competencia)\s*(\d{1,2})\b", t)
        if m and comps and comps != [None]:
            i = int(m.group(1)) - 1
            if 0 <= i < len(comps):
                col["competencia"] = comps[i].pk
        elif comps and comps != [None]:
            mejor, puntaje = None, 0
            for comp in comps:
                ct = _tokens(comp.nombre)
                p = len(ct & _tokens(col["titulo"])) / len(ct) if ct else 0
                if p > puntaje and p >= 0.5:
                    mejor, puntaje = comp, p
            if mejor:
                col["competencia"] = mejor.pk
        if col["competencia"]:
            usadas.add(col["competencia"])
    # por posición: si quedan columnas sin asignar y tantas competencias libres como columnas
    libres = [c for c in comps if c and c.pk not in usadas]
    sin = [c for c in notas if not c["competencia"]]
    if comps == [None] and notas:
        notas[0]["competencia"] = 0  # nota única del curso
    elif sin and len(sin) == len(libres):
        for col, comp in zip(sin, libres):
            col["competencia"] = comp.pk
    # conclusiones: a la columna de nota inmediatamente a su izquierda; si es una sola, todas juntas
    concl = [c for c in hoja["columnas"] if c["tipo"] == "conclusion"]
    for col in concl:
        izquierda = [n for n in notas if n["col"] < col["col"]]
        if len(concl) > 1 and izquierda and izquierda[-1].get("competencia") is not None:
            col["competencia"] = izquierda[-1]["competencia"]
        else:
            col["competencia"] = "todas"
    return hoja


def analizar(archivo, seccion, periodo):
    try:
        wb = load_workbook(archivo, data_only=False, keep_vba=str(getattr(archivo, "name", "")).lower().endswith(".xlsm"))
    except Exception:
        return None, "No se pudo abrir el archivo. Debe ser un Excel .xlsx o .xlsm."
    ctx = Contexto(seccion, periodo)
    hojas = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        h = _analizar_hoja(ws, ctx)
        if h:
            hojas.append(h)
    if not hojas:
        return None, ("No encontré a los estudiantes de esta sección en el archivo. Verifica que la plantilla sea "
                      f"de {seccion.grado.nombre} «{seccion.nombre}» y que los DNI o nombres coincidan con los del sistema.")
    encontrados = {a for h in hojas for _, a in h["filas"]}
    faltan = [f"{a.apellidos}, {a.nombres}" for a in ctx.alumnos if a.pk not in encontrados]
    return {"hojas": hojas, "faltan": faltan}, None


def llenar(ruta, nombre_archivo, analisis, seccion, periodo, sobrescribir=True):
    ctx = Contexto(seccion, periodo)
    wb = load_workbook(ruta, keep_vba=nombre_archivo.lower().endswith(".xlsm"))
    escritas, omitidas = 0, 0
    for h in analisis["hojas"]:
        if not h.get("asignacion"):
            continue
        ws = wb[h["nombre"]]
        asig = next((a for a in ctx.asignaciones if a.pk == h["asignacion"]), None)
        if asig is None:
            continue
        notas = {(n.alumno_id, n.competencia_id or 0): n for n in Nota.objects.filter(asignacion=asig, periodo=periodo)}
        comentarios = {c.alumno_id: c.texto for c in Comentario.objects.filter(asignacion=asig, periodo=periodo)}
        for fila, alumno_id in h["filas"]:
            for col in h["columnas"]:
                comp = col.get("competencia")
                if comp is None or comp == "":
                    continue
                if col["tipo"] == "nota":
                    n = notas.get((alumno_id, int(comp)))
                    valor = n.valor if n else None
                else:
                    if comp == "todas":
                        textos = [n.conclusion for (al, _), n in sorted(notas.items(), key=lambda kv: kv[0][1]) if al == alumno_id and n.conclusion]
                        valor = " ".join(textos) or comentarios.get(alumno_id)
                    else:
                        n = notas.get((alumno_id, int(comp)))
                        valor = n.conclusion if n and n.conclusion else None
                if valor in (None, ""):
                    continue
                celda = ws.cell(row=fila, column=col["col"])
                if isinstance(celda, MergedCell):
                    omitidas += 1
                    continue
                if celda.value not in (None, "") and not sobrescribir:
                    omitidas += 1
                    continue
                celda.value = valor
                como_texto(celda)  # una conclusión que empiece con "=" no se vuelve fórmula
                escritas += 1
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), escritas, omitidas
