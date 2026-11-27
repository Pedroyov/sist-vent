from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header

from core.permisos import modulo_activo, permiso_requerido, puede
from core.utils import dias

from . import servicios as s


def _comparar(request, desde, hasta, atajo):
    """Con qué se compara el periodo: ?comparar=anterior|anio|fechas (&c_desde, &c_hasta). En una fecha especial, por
    defecto con la del año pasado."""
    from datetime import date

    modo = request.GET.get("comparar") or ("anio" if atajo.startswith("esp:") else "anterior")
    if modo not in dict(s.COMPARAR):
        modo = "anterior"
    try:
        c_desde, c_hasta = date.fromisoformat(request.GET.get("c_desde", "")), date.fromisoformat(request.GET.get("c_hasta", ""))
    except ValueError:
        c_desde = c_hasta = None
        if modo == "fechas":
            modo = "anterior"
    d0, d1 = s.rango_comparado(desde, hasta, modo, c_desde, c_hasta)
    return modo, d0, d1


def _datos(request):
    desde, hasta, atajo = s.periodo(request)
    modo, d0, d1 = _comparar(request, desde, hasta, atajo)
    fechas, mensual = s.por_fecha(desde, hasta)
    hoy = timezone.localdate()
    d = {
        "desde": desde, "hasta": hasta, "atajo": atajo, "atajos": s.ATAJOS,
        "especiales": [(k, n, s.especial_cercana(k, hoy)) for k, n in s.FECHAS_ESPECIALES],
        "comparar": modo, "opciones_comparar": s.COMPARAR, "cmp": s.comparacion(desde, hasta, d0, d1),
        "r": s.resumen(desde, hasta, d0, d1), "fechas": fechas, "mensual": mensual,
        "horas": s.por_hora(desde, hasta), "semana": s.por_dia_semana(desde, hasta),
        "productos": s.productos(desde, hasta), "categorias": s.categorias(desde, hasta),
        "sin_ventas": s.sin_ventas(desde, hasta), "opciones": s.opciones(desde, hasta),
        "anuladas": s.anuladas(desde, hasta), "rebajas": s.cortesias_descuentos(desde, hasta), "cajas": s.cajas(desde, hasta),
        "ver_costos": puede(request.user, "productos.costos"),
        "con_mesas": modulo_activo(request.user, "mesas"), "con_clientes": modulo_activo(request.user, "clientes"),
        "con_productos": modulo_activo(request.user, "productos"), "con_delivery": modulo_activo(request.user, "delivery"),
        "con_citas": modulo_activo(request.user, "citas"),
    }
    from personal.reportes import de_negocio

    d["personal"] = de_negocio(desde, hasta)
    from ventas.conciliacion import para_reportes

    d["conciliacion"] = para_reportes(desde, hasta)
    d["con_caja"] = modulo_activo(request.user, "caja")
    if d["con_caja"]:
        from caja.servicios import gastos

        g = d["gastos"] = gastos(desde, hasta)
        # Ganancia real: la de las ventas (ya resta el costo de lo vendido) menos los demás gastos. Lo pagado a proveedores
        # no se resta otra vez: es mercadería, y su costo sale cuando se vende.
        g["ganancia_real"] = d["r"]["ganancia"] - g["operativos"]
    from compras.models import Compra

    if modulo_activo(request.user, "compras") or Compra.objects.filter(fecha__gte=desde, fecha__lte=hasta).exists():
        from compras.servicios import por_proveedor, registro

        d["compras"] = por_proveedor(desde, hasta)
        d["compras"]["registro"] = registro(desde, hasta)
    from core.models import Ajustes

    if Ajustes.cargar().usa_pagos:
        from personal.pagos import cuentas

        d["pagos"] = cuentas(desde, hasta)
    if d["con_mesas"] or d["con_delivery"]:
        d["mesas"] = s.mesas(desde, hasta)
    if d["con_clientes"]:
        d["deudores"] = s.deudores()
    d["inventario"] = s.inventario(desde, hasta)
    d["opciones_ingreso"] = sum((f["ingreso"] for f in d["opciones"]), s.CERO)
    fin = hasta
    if atajo == "mes":  # «Este mes» llega hasta hoy: la proyección es al último día del mes
        import calendar

        fin = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
    d["proyeccion"] = s.proyeccion(desde, fin, d["r"]["total"], hoy)
    d["futuro"] = desde > hoy  # una fecha especial que todavía no llega: sirve para preparar
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
             [f"Comparado con ({r['anterior']['desde']:%d/%m/%Y} al {r['anterior']['hasta']:%d/%m/%Y})", r["anterior"]["total"]],
             ["Variación %", r["variacion"]]]
    if d.get("proyeccion"):
        filas.append(["Proyección al cierre del periodo", d["proyeccion"]["total"]])
    if d["ver_costos"]:
        filas.append(["Ganancia aproximada", r["ganancia"]])
    if d.get("gastos"):
        g = d["gastos"]
        filas += [["Gastos (sin proveedores)", g["operativos"]], ["Pagos a proveedores", g["proveedores"]], ["Retiros del dueño", g["retiros"]]]
        if d["ver_costos"]:
            filas.append(["Ganancia real", g["ganancia_real"]])
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
    pe = d["personal"]
    v = pe["ver"]
    cab = ["Persona", "Cobró en caja", "Ventas que cobró", "Ventas S/", "Ticket promedio"]
    if v["cuotas"]:
        cab += ["Cuotas cobradas", "Cuotas S/"]
    if v["deudas"]:
        cab += ["Pagos de deudas", "Deudas S/"]
    if v["atendio"]:
        cab += ["Ventas que atendió", "Atendió S/"]
    if v["propinas"]:
        cab += ["Propinas"]
    if v["servicios"]:
        cab += ["Servicios", "Servicios S/", "Clientes", "Sin cita", "No vino", "Horas atendiendo", "Ocupación %", "Lo que más hizo"]
    if v["entregas"]:
        cab += ["Entregas"]
    cab += ["Generó"]
    if v["comisiones"]:
        cab += ["Comisión %", "Comisión S/"]
    filas = []
    for f in pe["filas"]:
        x = [f["nombre"], f["cobro"], f["ventas_n"], f["ventas"], f["promedio"] or ""]
        if v["cuotas"]:
            x += [f["cuotas_n"], f["cuotas"]]
        if v["deudas"]:
            x += [f["deudas_n"], f["deudas"]]
        if v["atendio"]:
            x += [f["atendio_n"], f["atendio"]]
        if v["propinas"]:
            x += [f["propinas"]]
        if v["servicios"]:
            x += [f["servicios"], f["servicios_total"], f["clientes"], f["sin_cita"], f["no_vino"], round(f["minutos"] / 60, 1),
                  f["ocupacion"] if f["ocupacion"] is not None else "", ", ".join(f"{n} ({k})" for n, k in f["top"])]
        if v["entregas"]:
            x += [f["entregas"]]
        x += [f["generado"]]
        if v["comisiones"]:
            x += [f["pct_comision"], f["comision"]]
        filas.append(x)
    hoja("Personal", cab, filas)
    if pe["tabla"]:
        hoja("Servicios por persona", ["Servicio"] + [p.nombre for p in pe["columnas"]] + ["Total"],
             [[f["servicio"]] + f["por"] + [f["total"]] for f in pe["tabla"]])
    if pe["tiempos"]:
        hoja("Tiempo real por servicio", ["Servicio", "Veces", "Real promedio (min)", "Mínimo (min)", "Máximo (min)", "Catálogo (min)", "Diferencia (min)"],
             [[t["servicio"], t["veces"], t["real"], t["minimo"], t["maximo"], t["catalogo"], t["diferencia"]] for t in pe["tiempos"]])
    if d.get("compras"):
        co = d["compras"]
        hoja("Compras por proveedor", ["Proveedor", "RUC", "Compras", "Total", "Se le debe hoy"],
             [[f["proveedor"].nombre, f["proveedor"].ruc, f["n"], f["total"], f["deuda"]] for f in co["filas"]])
        hoja("Registro de compras", ["Fecha", "Documento", "Serie", "Número", "RUC/DNI", "Proveedor", "Valor sin IGV", "IGV", "Total",
                                     "Forma de pago", "Vence", "Pagado", "Pendiente", "Estado"],
             [[c.fecha.strftime("%d/%m/%Y"), c.get_documento_display(), c.serie, c.numero, c.proveedor.ruc, c.proveedor.nombre,
               c.base if c.igv else "", c.igv if c.igv else "", c.total, "Crédito" if c.vence else "Contado",
               c.vence.strftime("%d/%m/%Y") if c.vence else "", c.pagado, c.saldo, c.estado] for c in co["registro"]])
    if d.get("pagos"):
        hoja("Pagos al personal", ["Persona", "Sueldo", "Comisión", "Le toca", "Pagado", "Falta"],
             [[f["persona"].nombre, f["sueldo"], f["comision"], f["toca"], f["pagado"], f["falta"]] for f in d["pagos"]["filas"]])
    if d.get("gastos"):
        from caja.models import MovimientoCaja

        hoja("Gastos", ["Motivo", "Veces", "Total"], [[f["etiqueta"], f["n"], f["total"]] for f in d["gastos"]["filas"]])
        hoja("Gastos (detalle)", ["Fecha", "Motivo", "Detalle", "Persona", "Monto", "De dónde", "Registró"],
             [[timezone.localtime(m.fecha).strftime("%d/%m/%Y %H:%M"), m.motivo, m.concepto, m.persona.nombre if m.persona else "", m.monto,
               f"Caja {m.sesion.numero}" if m.sesion else "Fuera de caja", m.usuario.get_full_name() or m.usuario.username]
              for m in MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO, **dias("fecha", d["desde"], d["hasta"]))
              .select_related("sesion", "usuario", "persona").order_by("fecha") if m.es_gasto])
    if d["con_mesas"]:
        hoja("Platos quitados", ["Fecha", "Mesa", "Plato", "Cantidad", "Valor", "Motivo", "Mozo", "Quitó"],
             [[timezone.localtime(i.creado).strftime("%d/%m/%Y %H:%M"), i.cuenta.titulo, i.descripcion, i.cantidad, i.subtotal,
               i.motivo_anulacion, i.cuenta.mozo.get_full_name(), i.anulado_por.get_full_name() if i.anulado_por else ""]
              for i in d["mesas"]["quitados"]])
    if d["con_clientes"]:
        hoja("Deudores", ["Cliente", "Documento", "Debe", "Vencido", "Días de atraso", "Días sin pagar", "Celular"],
             [[f["cliente"].nombre, f["cliente"].documento, f["saldo"], f["vencido"], f["dias_vencido"] or "", f["dias"], f["cliente"].telefono]
              for f in d["deudores"]["filas"]])
    hoja("Cajas", ["Cajero", "Cajas cerradas", "Con diferencia", "Faltante", "Sobrante"],
         [[f["etiqueta"], f["cajas"], f["con_diferencia"], f["faltante"], f["sobrante"]] for f in d["cajas"]["filas"]])
    if d["conciliacion"]["hay"]:
        hoja("Conciliación", ["Método", "Días conciliados", "Según el sistema", "Según el banco", "Diferencia"],
             [[f["nombre"], f["n"], f["sistema"], f["banco"], f["dif"]] for f in d["conciliacion"]["por_metodo"]])
        if d["conciliacion"]["por_cajero"]:
            hoja("No llegaron", ["Cobró", "Cobros", "Monto"], [[f["etiqueta"], f["n"], f["total"]] for f in d["conciliacion"]["por_cajero"]])
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
    cm = d["cmp"]
    hoja("Comparación", ["", f"{cm['ahora']['desde']:%d/%m/%Y} al {cm['ahora']['hasta']:%d/%m/%Y}",
                         f"{cm['antes']['desde']:%d/%m/%Y} al {cm['antes']['hasta']:%d/%m/%Y}", "Variación %"],
         [["Total vendido", cm["ahora"]["total"], cm["antes"]["total"], cm["ahora"]["var_total"]],
          ["Ventas", cm["ahora"]["n"], cm["antes"]["n"], cm["ahora"]["var_n"]],
          ["Ticket promedio", cm["ahora"]["promedio"], cm["antes"]["promedio"], cm["ahora"]["var_promedio"]],
          ["Venta por día", cm["ahora"]["por_dia"], cm["antes"]["por_dia"], cm["ahora"]["var_por_dia"]], [],
          ["Producto", "Vendido ahora", "Vendido antes", "Diferencia S/"]]
         + [[f["nombre"], f["total_ahora"], f["total_antes"], f["dif"]] for f in cm["subieron"] + cm["bajaron"]])
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"reporte_{d['desde']:%Y%m%d}_{d['hasta']:%Y%m%d}.xlsx")
    return resp


@permiso_requerido("reportes.ver")
def dinero(request):
    """Flujo de caja día por día: lo que entró, lo que salió y dónde quedó."""
    from .flujo import por_dia

    desde, hasta, atajo = s.periodo(request)
    d = por_dia(desde, hasta)
    if request.GET.get("excel"):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        from core.excel import a_bytes

        wb = Workbook()
        ws = wb.active
        ws.title = "Dinero del día"
        ws.append(["Día", "Efectivo", *d["metodos"], "Otros ingresos", "Total entró", "Salió de cajas", "Salió fuera de caja",
                   "Total salió", "Neto", "Retirado (dueño)", "Quedó en cajones", "Diferencia de caja", "Diferencia con el banco",
                   "Fiado vendido (no es dinero)"])
        for c in ws[1]:
            c.font = Font(bold=True)

        def fila(etiqueta, f, metodos, quedo):
            return [etiqueta, f["efectivo"], *[m["total"] for m in metodos], f["ingresos"], f["entro"], f["salio_cajas"], f["salio_fuera"],
                    f["salio"], f["neto"], f["retirado"], quedo, f["dif_caja"], f["dif_conciliacion"], f["fiado"]]

        for f in reversed(d["filas"]):
            ws.append([float(x) if hasattr(x, "quantize") else x for x in fila(f["dia"].strftime("%d/%m/%Y"), f, f["metodos"], f["quedo"])])
        ws.append([float(x) if hasattr(x, "quantize") else x for x in fila("Total", d["total"], d["total"]["metodos"], None)])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        ws.freeze_panes = "B2"
        resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = content_disposition_header(True, f"dinero_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx")
        return resp
    query = request.GET.copy()
    query.pop("excel", None)
    return render(request, "reportes/dinero.html", {**d, "desde": desde, "hasta": hasta, "atajo": atajo, "atajos": s.ATAJOS,
                                                    "query": query, "con_caja": modulo_activo(request.user, "caja")})
