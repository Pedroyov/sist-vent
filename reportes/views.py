from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header

from core.permisos import modulo_activo, permiso_requerido, puede

from . import servicios as s


def _datos(request):
    desde, hasta, atajo = s.periodo(request)
    fechas, mensual = s.por_fecha(desde, hasta)
    d = {
        "desde": desde, "hasta": hasta, "atajo": atajo, "atajos": s.ATAJOS,
        "r": s.resumen(desde, hasta), "fechas": fechas, "mensual": mensual,
        "horas": s.por_hora(desde, hasta), "semana": s.por_dia_semana(desde, hasta),
        "productos": s.productos(desde, hasta), "categorias": s.categorias(desde, hasta),
        "sin_ventas": s.sin_ventas(desde, hasta), "opciones": s.opciones(desde, hasta), "vendedores": s.por_usuario(desde, hasta, "usuario"),
        "anuladas": s.anuladas(desde, hasta), "rebajas": s.cortesias_descuentos(desde, hasta), "cajas": s.cajas(desde, hasta),
        "ver_costos": puede(request.user, "productos.costos"),
        "con_mesas": modulo_activo(request.user, "mesas"), "con_clientes": modulo_activo(request.user, "clientes"),
        "con_productos": modulo_activo(request.user, "productos"),
    }
    if d["con_mesas"]:
        d["mozos"] = s.por_usuario(desde, hasta, "atendio")
        d["mesas"] = s.mesas(desde, hasta)
    if d["con_clientes"]:
        d["deudores"] = s.deudores()
    d["inventario"] = s.inventario(desde, hasta)
    d["opciones_ingreso"] = sum((f["ingreso"] for f in d["opciones"]), s.CERO)
    d["top"] = d["productos"][:20]
    d["menos"] = [p for p in reversed(d["productos"][20:])][:10] if len(d["productos"]) > 20 else []
    return d


@permiso_requerido("reportes.ver")
def inicio(request):
    d = _datos(request)
    if request.GET.get("excel"):
        return _excel(d)
    query = request.GET.copy()
    query.pop("excel", None)
    d["query"] = query
    return render(request, "reportes/inicio.html", d)


def _excel(d):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from core.excel import a_bytes

    wb = Workbook()
    azul = PatternFill("solid", fgColor="0D6EFD")

    def hoja(titulo, encabezados, filas, primera=False):
        ws = wb.active if primera else wb.create_sheet()
        ws.title = titulo[:31]
        ws.append(encabezados)
        for i, _ in enumerate(encabezados, start=1):
            celda = ws.cell(row=1, column=i)
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = azul
            ws.column_dimensions[get_column_letter(i)].width = 14 if i > 1 else 32
        for f in filas:
            ws.append([float(x) if hasattr(x, "quantize") else x for x in f])
        ws.freeze_panes = "A2"
        return ws

    r = d["r"]
    filas = [["Periodo", f"{d['desde']:%d/%m/%Y} al {d['hasta']:%d/%m/%Y}"], ["Total vendido", r["total"]], ["Ventas", r["n"]],
             ["Ticket promedio", r["promedio"]], ["Promedio por día", r["por_dia"]], ["Descuentos", r["descuentos"]],
             ["Propinas", r["propinas"]], ["Anuladas (cantidad)", r["anuladas"]], ["Anuladas (monto)", r["anuladas_monto"]],
             ["Periodo anterior", r["anterior"]["total"]], ["Variación %", r["variacion"]]]
    if d["ver_costos"]:
        filas.append(["Ganancia aproximada", r["ganancia"]])
    filas += [[f"Cobrado con {m['metodo']}", m["total"]] for m in r["metodos"]]
    hoja("Resumen", ["Concepto", "Valor"], filas, primera=True)
    hoja("Por mes" if d["mensual"] else "Por día", ["Fecha", "Total", "Ventas"], [[f["etiqueta"], f["total"], f["n"]] for f in d["fechas"]])
    hoja("Por hora", ["Hora", "Total", "Ventas"], [[f["etiqueta"], f["total"], f["n"]] for f in d["horas"]])
    hoja("Por día de semana", ["Día", "Total", "Ventas"], [[f["etiqueta"], f["total"], f["n"]] for f in d["semana"]])
    cab = ["Producto", "Categoría", "Cantidad", "Total", "% del total", "Ventas"] + (["Costo", "Ganancia"] if d["ver_costos"] else [])
    hoja("Productos", cab, [[p["nombre"], p["categoria"], p["cantidad"], p["total"], p["participacion"], p["n_ventas"]]
                            + ([p["costo"], p["ganancia"]] if d["ver_costos"] else []) for p in d["productos"]])
    hoja("Categorías", ["Categoría", "Total", "% del total"] + (["Ganancia"] if d["ver_costos"] else []),
         [[f["etiqueta"], f["total"], f["participacion"]] + ([f["ganancia"]] if d["ver_costos"] else []) for f in d["categorias"]])
    hoja("Opciones y adicionales", ["Opción", "Grupo", "Veces", "Cobrado aparte"],
         [[f["etiqueta"], f["grupo"], f["veces"], f["ingreso"]] for f in d["opciones"]])
    hoja("Sin ventas", ["Producto", "Categoría"], [[p.nombre, p.categoria.nombre if p.categoria else ""] for p in d["sin_ventas"]])
    hoja("Vendedores", ["Cobró", "Total", "Ventas", "Ticket promedio"], [[f["etiqueta"], f["total"], f["n"], f["promedio"]] for f in d["vendedores"]])
    if d["con_mesas"]:
        hoja("Mozos", ["Mozo", "Total", "Ventas", "Ticket promedio", "Propinas"],
             [[f["etiqueta"], f["total"], f["n"], f["promedio"], f["propinas"]] for f in d["mozos"]])
        hoja("Platos quitados", ["Fecha", "Mesa", "Plato", "Cantidad", "Valor", "Motivo", "Mozo", "Quitó"],
             [[timezone.localtime(i.creado).strftime("%d/%m/%Y %H:%M"), i.cuenta.titulo, i.descripcion, i.cantidad, i.subtotal,
               i.motivo_anulacion, i.cuenta.mozo.get_full_name(), i.anulado_por.get_full_name() if i.anulado_por else ""]
              for i in d["mesas"]["quitados"]])
    if d["con_clientes"]:
        hoja("Deudores", ["Cliente", "Documento", "Debe", "Días sin pagar", "Celular"],
             [[f["cliente"].nombre, f["cliente"].documento, f["saldo"], f["dias"], f["cliente"].telefono] for f in d["deudores"]["filas"]])
    hoja("Cajas", ["Cajero", "Cajas cerradas", "Con diferencia", "Faltante", "Sobrante"],
         [[f["etiqueta"], f["cajas"], f["con_diferencia"], f["faltante"], f["sobrante"]] for f in d["cajas"]["filas"]])
    hoja("Anuladas", ["N°", "Fecha", "Total", "Motivo", "Vendió", "Anuló"],
         [[v.numero_str, timezone.localtime(v.fecha).strftime("%d/%m/%Y %H:%M"), v.total, v.motivo_anulacion,
           v.usuario.get_full_name(), v.anulada_por.get_full_name() if v.anulada_por else ""] for v in d["anuladas"]])
    rb = d["rebajas"]
    if rb["cortesias"] or rb["descuentos"]:
        fecha = lambda f: timezone.localtime(f).strftime("%d/%m/%Y %H:%M")
        nom = lambda u: (u.get_full_name() or u.username) if u else ""
        hoja("Cortesías y descuentos", ["Fecha", "N°", "Tipo", "Detalle", "Valor", "Motivo", "Atendió", "Autorizó"],
             [[fecha(i.venta.fecha), i.venta.numero_str, "Cortesía", f"{i.cantidad:g} × {i.descripcion}", i.valor, i.cortesia_motivo,
               nom(i.venta.atendio or i.venta.usuario), nom(i.cortesia_por)] for i in rb["cortesias"]]
             + [[fecha(v.fecha), v.numero_str, "Descuento", f"Venta de {v.subtotal}", v.descuento, v.descuento_motivo,
                 nom(v.atendio or v.usuario), nom(v.descuento_por)] for v in rb["descuentos"]])
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"reporte_{d['desde']:%Y%m%d}_{d['hasta']:%Y%m%d}.xlsx")
    return resp
