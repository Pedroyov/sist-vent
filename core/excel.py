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
