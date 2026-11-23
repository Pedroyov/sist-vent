"""Utilidades para los Excel que genera el sistema."""
from io import BytesIO

PELIGROSOS = ("=", "+", "-", "@", "\t", "\r")


def como_texto(celda):
    """Evita la 'inyección de fórmulas': un nombre escrito como =HIPERVINCULO(...) se guarda como texto."""
    if celda.data_type == "f" or (isinstance(celda.value, str) and celda.value.startswith(PELIGROSOS)):
        celda.data_type = "s"


def a_bytes(wb):
    """Guarda el libro sin fórmulas: todo lo que genera el sistema son datos, nunca fórmulas."""
    for ws in wb.worksheets:
        for fila in ws.iter_rows():
            for celda in fila:
                if celda.data_type == "f":
                    celda.data_type = "s"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def descargar(nombre, hojas):
    """Un Excel listo para bajar. hojas = [(título, encabezados, filas)]; el archivo sale como «nombre_AAAAMMDD.xlsx».
    Encabezados en negrita, primera fila fija y anchos según el contenido. Se usa en todas las pantallas con botón Excel."""
    from decimal import Decimal

    from django.http import HttpResponse
    from django.utils import timezone
    from django.utils.http import content_disposition_header
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for titulo, encabezados, filas in hojas:
        ws = wb.create_sheet(str(titulo)[:31])
        ws.append(list(encabezados))
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        anchos = [len(str(e)) for e in encabezados]
        for fila in filas:
            fila = [float(v) if isinstance(v, Decimal) else v for v in fila]
            ws.append(fila)
            for celda in ws[ws.max_row]:
                como_texto(celda)
            for i, v in enumerate(fila[:len(anchos)]):
                anchos[i] = max(anchos[i], min(len(str(v if v is not None else "")), 50))
        for i, ancho in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(i)].width = ancho + 2
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"{nombre}_{timezone.localdate():%Y%m%d}.xlsx")
    return resp
