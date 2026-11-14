"""Plantilla, importación y exportación de productos en Excel (una fila por variante)."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.excel import a_bytes

from .models import CERO, Categoria, MovimientoStock, Producto, Unidad, Variante
from .servicios import ajustar_a, asegurar_variante_unica, generar_variantes, mover_stock

# (clave, encabezado, obligatorio, ancho)
COLUMNAS = [
    ("nombre", "Producto", True, 34),
    ("variante", "Variante", False, 16),
    ("codigo", "Código", False, 16),
    ("categoria", "Categoría", False, 18),
    ("tipo", "Tipo", False, 11),
    ("unidad", "Unidad", False, 10),
    ("precio", "Precio", True, 10),
    ("costo", "Costo", False, 10),
    ("stock", "Stock", False, 10),
    ("stock_minimo", "Stock mínimo", False, 12),
]
ALIAS = {"nombre del producto": "nombre", "descripcion": "nombre", "talla": "variante", "codigo de barras": "codigo",
         "precio de venta": "precio", "precio venta": "precio", "cantidad": "stock", "minimo": "stock_minimo"}
AZUL = PatternFill("solid", fgColor="0D6EFD")
MAX_FILAS = 3000


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).replace("*", "").strip().lower()


UNIDADES = {_norm(v): k for k, v in Unidad.choices} | {_norm(k): k for k, _ in Unidad.choices} | {
    "und": "UND", "unid": "UND", "u": "UND", "kilo": "KG", "kilos": "KG", "litros": "LT", "metros": "MT", "pqt": "PAQ"}


def _encabezados(ws):
    for i, (_, titulo, obligatorio, ancho) in enumerate(COLUMNAS, start=1):
        c = ws.cell(row=1, column=i, value=titulo + (" *" if obligatorio else ""))
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = AZUL
        c.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = "A2"


def _num(v):
    return float(v) if v is not None else None


def plantilla():
    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"
    _encabezados(ws)
    col_codigo = get_column_letter([c[0] for c in COLUMNAS].index("codigo") + 1)
    for fila in range(2, 2002):
        ws[f"{col_codigo}{fila}"].number_format = "@"  # no perder ceros ni dígitos del código de barras
    for clave, opciones in (("tipo", '"Producto,Servicio"'), ("unidad", '"' + ",".join(v for k, v in Unidad.choices if k != "SRV") + '"')):
        dv = DataValidation(type="list", formula1=opciones, allow_blank=True)
        col = get_column_letter([c[0] for c in COLUMNAS].index(clave) + 1)
        dv.add(f"{col}2:{col}2001")
        ws.add_data_validation(dv)

    ayuda = wb.create_sheet("Instrucciones")
    lineas = [
        "CÓMO LLENAR LA PLANTILLA",
        "",
        "• Una fila por producto. Las columnas con * son obligatorias.",
        "• Si un producto tiene tallas, colores o tamaños, pon una fila por cada uno con el MISMO nombre",
        "  de producto y la talla/color en la columna Variante (por ejemplo «M / Negro»).",
        "• Código: el código de barras o tu código interno. No se puede repetir.",
        "• Tipo: Producto o Servicio (vacío = Producto). Los servicios no llevan stock.",
        "• Unidad: Unidad, Kilo, Litro, Metro, Paquete, Caja, Docena o Par (vacío = Unidad).",
        "• Precio y costo: solo el número, con punto decimal (por ejemplo 12.50).",
        "• Stock: lo que tienes ahora. Si el producto ya existe, se ajusta a ese número.",
        "• Si el producto ya existe (mismo código, o mismo nombre y variante), se actualizan sus datos.",
        "• La categoría se crea sola si no existe.",
    ]
    for i, t in enumerate(lineas, start=1):
        ayuda.cell(row=i, column=1, value=t).font = Font(bold=(i == 1), size=12 if i == 1 else 11)
    ayuda.column_dimensions["A"].width = 100
    fila = len(lineas) + 2
    ayuda.cell(row=fila, column=1, value="EJEMPLOS").font = Font(bold=True)
    ejemplos = [
        ["Gaseosa Inca Kola 500 ml", "", "7750182001236", "Bebidas", "Producto", "Unidad", 2.50, 1.80, 48, 12],
        ["Polo básico algodón", "M / Negro", "", "Polos", "Producto", "Unidad", 29.90, 15, 6, 2],
        ["Polo básico algodón", "L / Negro", "", "Polos", "Producto", "Unidad", 29.90, 15, 4, 2],
        ["Arroz extra", "", "", "Abarrotes", "Producto", "Kilo", 4.20, 3.50, 50.5, 10],
        ["Corte de cabello adulto", "", "", "Cortes", "Servicio", "", 25, "", "", ""],
    ]
    for j, (_, titulo, _, _) in enumerate(COLUMNAS, start=1):
        ayuda.cell(row=fila + 1, column=j, value=titulo).font = Font(bold=True)
        for k, ej in enumerate(ejemplos):
            ayuda.cell(row=fila + 2 + k, column=j, value=ej[j - 1])
    return a_bytes(wb)


def exportar(variantes, ver_costos=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"
    _encabezados(ws)
    extra = ["Activo"]
    for i, t in enumerate(extra, start=len(COLUMNAS) + 1):
        c = ws.cell(row=1, column=i, value=t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = AZUL
    for v in variantes:
        p = v.producto
        ws.append([
            p.nombre, v.nombre, v.codigo, p.categoria.nombre if p.categoria else "", p.get_tipo_display(),
            "" if p.es_servicio else p.get_unidad_display(), _num(v.precio_venta),
            _num(v.costo_efectivo) if ver_costos else None,
            _num(v.stock) if p.maneja_stock else None, _num(p.stock_minimo) if p.maneja_stock else None,
            "Sí" if (p.activo and v.activa) else "No",
        ])
    if not ver_costos:
        ws.delete_cols([c[0] for c in COLUMNAS].index("costo") + 1)
    return a_bytes(wb)


# --- Importar ----------------------------------------------------------------

def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _decimal(v, campo, errores, obligatorio=False):
    if v is None or str(v).strip() == "":
        if obligatorio:
            errores.append(f"falta {campo}")
        return None
    try:
        d = Decimal(str(v).replace(",", ".").replace("S/", "").strip())
    except InvalidOperation:
        errores.append(f"{campo} no es un número")
        return None
    if d < 0:
        errores.append(f"{campo} no puede ser negativo")
        return None
    return d


def leer(archivo):
    """Revisa el Excel sin guardar nada. Devuelve (filas, errores_generales).
    Cada fila: dict con los datos, 'fila', 'errores' (lista) y 'accion' (nuevo/actualizar)."""
    try:
        wb = load_workbook(archivo, read_only=True, data_only=True)
    except Exception:
        return [], ["No se pudo abrir el archivo. ¿Es un Excel (.xlsx) válido?"]
    ws = wb.worksheets[0]
    filas_ws = ws.iter_rows(values_only=True)
    try:
        cabecera = next(filas_ws)
    except StopIteration:
        return [], ["El archivo está vacío."]
    titulos = {_norm(t): k for k, t, _, _ in COLUMNAS} | ALIAS
    posiciones = {}
    for i, celda in enumerate(cabecera):
        clave = titulos.get(_norm(celda))
        if clave and clave not in posiciones:
            posiciones[clave] = i
    faltan = [t for k, t, ob, _ in COLUMNAS if ob and k not in posiciones]
    if faltan:
        return [], [f"No encuentro la columna «{', '.join(faltan)}» en la primera fila. Usa la plantilla."]

    filas, codigos = [], {}
    for n, valores in enumerate(filas_ws, start=2):
        if not any(v not in (None, "") for v in valores):
            continue
        if len(filas) >= MAX_FILAS:
            return filas, [f"Máximo {MAX_FILAS} filas por archivo. Divide el Excel en partes."]
        bruto = {k: (valores[i] if i < len(valores) else None) for k, i in posiciones.items()}
        err = []
        f = {"fila": n, "nombre": _texto(bruto.get("nombre"))[:150], "variante": _texto(bruto.get("variante")).replace(",", " ")[:80],
             "codigo": _texto(bruto.get("codigo"))[:50], "categoria": _texto(bruto.get("categoria"))[:80]}
        if not f["nombre"]:
            err.append("falta el nombre del producto")
        tipo = _norm(bruto.get("tipo"))
        f["tipo"] = "S" if tipo.startswith("serv") else "P"
        if tipo and not tipo.startswith(("serv", "prod")):
            err.append("tipo debe ser Producto o Servicio")
        unidad = _norm(bruto.get("unidad"))
        f["unidad"] = "SRV" if f["tipo"] == "S" else UNIDADES.get(unidad, "UND" if not unidad else None)
        if f["unidad"] is None:
            err.append(f"unidad «{bruto.get('unidad')}» no reconocida")
        for clave, campo, ob in (("precio", "precio", True), ("costo", "costo", False), ("stock", "stock", False),
                                 ("stock_minimo", "stock mínimo", False)):
            d = _decimal(bruto.get(clave), campo, err, ob)
            f[clave] = str(d) if d is not None else None
        if f["codigo"]:
            if f["codigo"].lower() in codigos:
                err.append(f"código repetido (también en la fila {codigos[f['codigo'].lower()]})")
            codigos[f["codigo"].lower()] = n
        f["errores"] = err
        filas.append(f)
    if not filas:
        return [], ["No hay productos en el archivo (solo encabezados)."]

    # ¿Qué hay ya en el sistema?
    con_y_sin = {}
    for f in filas:
        con_y_sin.setdefault(f["nombre"].lower(), set()).add(bool(f["variante"]))
    for f in filas:
        if f["errores"]:
            continue
        existente = None
        if f["codigo"]:
            existente = Variante.objects.filter(codigo__iexact=f["codigo"]).select_related("producto").first()
            if existente and existente.producto.nombre.lower() != f["nombre"].lower():
                f["errores"].append(f"el código ya es de «{existente.nombre_completo}»")
                continue
        if existente is None:
            prod = Producto.objects.filter(nombre__iexact=f["nombre"]).first()
            if prod:
                existente = prod.variantes.filter(nombre__iexact=f["variante"], activa=True).first()
                if not f["variante"] and prod.tiene_variantes:
                    f["errores"].append("ese producto ya tiene variantes: indica cuál en la columna Variante")
                unica = prod.variante_unica()
                if f["variante"] and not existente and unica and unica.activa and unica.stock != CERO:
                    f["errores"].append("ese producto tiene stock sin variante: ajústalo a 0 antes de agregarle variantes")
        if len(con_y_sin[f["nombre"].lower()]) > 1:
            f["errores"].append("el mismo producto tiene filas con y sin variante")
        f["accion"] = "actualizar" if existente else "nuevo"
        f["variante_id"] = existente.pk if existente else None
    return filas, []


@transaction.atomic
def importar(filas, usuario):
    """Guarda las filas ya revisadas (sin errores). Devuelve (creados, actualizados)."""
    creados = actualizados = 0
    categorias = {}
    productos = {}
    for f in filas:
        cat = None
        if f["categoria"]:
            clave = f["categoria"].lower()
            if clave not in categorias:
                categorias[clave] = (Categoria.objects.filter(nombre__iexact=f["categoria"]).first()
                                     or Categoria.objects.create(nombre=f["categoria"]))
            cat = categorias[clave]
        precio = Decimal(f["precio"])
        costo = Decimal(f["costo"]) if f["costo"] is not None else None
        variante = Variante.objects.select_related("producto").filter(pk=f["variante_id"]).first() if f["variante_id"] else None
        clave_p = f["nombre"].lower()
        prod = variante.producto if variante else productos.get(clave_p) or Producto.objects.filter(nombre__iexact=f["nombre"]).first()
        nuevo_producto = prod is None
        if nuevo_producto:
            prod = Producto(nombre=f["nombre"], precio=precio, costo=costo)
        if clave_p not in productos:  # los datos del producto se toman de su primera fila
            prod.tipo = f["tipo"]
            prod.unidad = f["unidad"]
            if cat:
                prod.categoria = cat
            if not f["variante"] or nuevo_producto:
                prod.precio = precio
                if costo is not None:
                    prod.costo = costo
            if f["stock_minimo"] is not None:
                prod.stock_minimo = Decimal(f["stock_minimo"])
            prod.maneja_stock = prod.tipo == "P" and (prod.maneja_stock or nuevo_producto)
            prod.save()
            productos[clave_p] = prod

        if variante is None:
            if f["variante"]:
                generar_variantes(prod, f["variante"])
                variante = prod.variantes.get(nombre__iexact=f["variante"])
            else:
                variante = asegurar_variante_unica(prod)
            creados += 1
        else:
            actualizados += 1
        if f["variante"]:
            variante.precio = None if precio == prod.precio else precio
            variante.costo = None if costo is None or costo == prod.costo else costo
        if f["codigo"]:
            variante.codigo = f["codigo"]
        variante.activa = True
        variante.save()

        if prod.maneja_stock and f["stock"] is not None:
            stock = Decimal(f["stock"])
            if not variante.movimientos.exists() and variante.stock == CERO:
                if stock:
                    mover_stock(variante, stock, MovimientoStock.Tipo.INICIAL, usuario, "Importación Excel")
            else:
                ajustar_a(variante, stock, usuario, "Importación Excel")
    return creados, actualizados
