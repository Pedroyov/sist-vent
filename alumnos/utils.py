"""Utilidades compartidas: filtro por nivel / grado / sección."""
from django.db.models import Q

from core.models import Seccion


def opciones_en(anio):
    """Opciones del selector "Grado / sección" (solo lo que existe en el año).
    Valores: n<id> = nivel, g<id> = grado, s<id> = sección."""
    secciones = Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre"
    )
    opciones, nivel_actual, grado_actual = [], None, None
    for sec in secciones:
        if sec.grado.nivel_id != nivel_actual:
            nivel_actual = sec.grado.nivel_id
            opciones.append((f"n{nivel_actual}", sec.grado.nivel.nombre, 0))
        if sec.grado_id != grado_actual:
            grado_actual = sec.grado_id
            opciones.append((f"g{grado_actual}", sec.grado.nombre, 1))
        opciones.append((f"s{sec.pk}", f"{sec.grado.nombre} «{sec.nombre}»", 2))
    return opciones


def filtro_en(en, prefijo="seccion"):
    """Q para filtrar matrículas según el valor del selector. prefijo: ruta hasta la sección."""
    if not en or len(en) < 2 or not en[1:].isdigit():
        return Q()
    tipo, pk = en[0], en[1:]
    if tipo == "s":
        return Q(**{f"{prefijo}_id": pk})
    if tipo == "g":
        return Q(**{f"{prefijo}__grado_id": pk})
    if tipo == "n":
        return Q(**{f"{prefijo}__grado__nivel_id": pk})
    return Q()
