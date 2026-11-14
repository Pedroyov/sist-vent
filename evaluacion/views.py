from django import forms
from django.utils.http import content_disposition_header
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from academico.models import Asignacion, Curso
from alumnos.models import Alumno
from core.excel import a_bytes
from core.models import AnioLectivo, Nivel, Periodo, Seccion
from core.utils import entero
from core.permisos import permiso_requerido, puede, requiere_modulo

from . import servicios as sv
from .models import LETRAS, Comentario, Competencia, Conducta, ConfigEvaluacion, Nota


def _periodo(request, anio):
    pk = request.GET.get("periodo") or request.POST.get("periodo")
    if pk and str(pk).isdigit():
        p = Periodo.objects.filter(pk=pk, anio_lectivo=anio).first()
        if p:
            return p
    return sv.periodo_actual(anio)


# --- Inicio: mis cursos -----------------------------------------------------

@permiso_requerido("notas.registrar", "notas.todas")
def inicio(request):
    anio = AnioLectivo.actual()
    if anio is None:
        return redirect("core:inicio")
    periodo = _periodo(request, anio)
    if periodo is None:
        messages.warning(request, "Primero crea los periodos (bimestres o trimestres) del año.")
        return redirect("core:inicio")
    es_dir = sv.es_direccion(request.user)
    asignaciones = Asignacion.objects.filter(seccion__anio_lectivo=anio, curso__activo=True).select_related(
        "curso", "seccion__grado__nivel", "docente").order_by(
        "seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre", "curso__orden")
    tutorias = Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel")
    seccion_filtro = request.GET.get("seccion", "")
    if not es_dir:
        asignaciones = asignaciones.filter(docente=request.user)
        tutorias = tutorias.filter(tutor=request.user)
    elif seccion_filtro.isdigit():
        asignaciones = asignaciones.filter(seccion_id=seccion_filtro)
        tutorias = tutorias.filter(pk=seccion_filtro)
    asignaciones = list(asignaciones)
    avance = sv.esperadas_y_registradas(asignaciones, periodo)
    for a in asignaciones:
        a.hechas, a.esperadas = avance[a.pk]
        a.pct = round(100 * a.hechas / a.esperadas) if a.esperadas else 0
    for s in tutorias:
        config = ConfigEvaluacion.de(anio, s.grado.nivel)
        s.con_conducta = config.conducta
        s.hechas = Conducta.objects.filter(seccion=s, periodo=periodo).exclude(numero__isnull=True, letra="").count()
        s.esperadas = len(sv.alumnos_periodo(s, periodo))
    return render(request, "evaluacion/inicio.html", {
        "anio": anio, "periodo": periodo, "periodos": anio.periodos.all(), "asignaciones": asignaciones,
        "tutorias": [s for s in tutorias if s.con_conducta], "es_dir": es_dir,
        "secciones": Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel").order_by(
            "grado__nivel__orden", "grado__orden", "nombre") if es_dir else [],
        "seccion_filtro": seccion_filtro,
    })


# --- Registro de notas de un curso ------------------------------------------

@permiso_requerido("notas.registrar", "notas.todas")
def registro(request, asignacion_pk):
    a = get_object_or_404(Asignacion.objects.select_related("curso", "seccion__grado__nivel", "seccion__anio_lectivo", "docente"), pk=asignacion_pk)
    if not sv.puede_calificar(request.user, a):
        raise PermissionDenied
    anio = a.seccion.anio_lectivo
    periodo = _periodo(request, anio)
    config = ConfigEvaluacion.de(anio, a.seccion.grado.nivel)
    comps = sv.competencias_de(a, config)
    alumnos = sv.alumnos_periodo(a.seccion, periodo)
    cerrado = periodo.notas_cerradas and not sv.es_direccion(request.user)

    if request.method == "POST":
        if cerrado:
            messages.error(request, "Las notas de este periodo están cerradas. Pide a Dirección que las abra.")
            return redirect(f"{reverse('evaluacion:registro', args=[a.pk])}?periodo={periodo.pk}")
        errores, sin_conclusion = [], 0
        with transaction.atomic():
            for al in alumnos:
                for comp in comps:
                    clave = f"n_{al.pk}_{comp.pk if comp else 0}"
                    if clave not in request.POST:
                        continue
                    numero, letra, error = sv.leer_valor(request.POST.get(clave), config)
                    if error:
                        errores.append(f"{al.nombres.title()} {al.apellido_paterno.title()}: {error}")
                        continue
                    filtro = {"alumno": al, "asignacion": a, "periodo": periodo, "competencia": comp}
                    conclusion = request.POST.get(f"d_{al.pk}_{comp.pk if comp else 0}", "").strip()[:1000]
                    if numero is None and not letra:
                        Nota.objects.filter(**filtro).delete()
                    else:
                        Nota.objects.update_or_create(**filtro, defaults={"numero": numero, "letra": letra, "conclusion": conclusion})
                        if letra == "C" and not conclusion:
                            sin_conclusion += 1
                if config.comentarios and f"c_{al.pk}" in request.POST:
                    texto = request.POST.get(f"c_{al.pk}", "").strip()[:600]
                    if texto:
                        Comentario.objects.update_or_create(alumno=al, asignacion=a, periodo=periodo, defaults={"texto": texto})
                    else:
                        Comentario.objects.filter(alumno=al, asignacion=a, periodo=periodo).delete()
        if errores:
            for e in errores[:8]:
                messages.error(request, e)
            messages.warning(request, "Las demás notas se guardaron. Corrige las marcadas.")
        else:
            messages.success(request, f"Notas de {a.curso} ({a.seccion.grado.nombre} {a.seccion.nombre}) guardadas.")
        if sin_conclusion:
            messages.warning(request, f"{sin_conclusion} calificación{'es' if sin_conclusion != 1 else ''} en C sin conclusión descriptiva (el SIAGIE la exige). Usa el lápiz junto a la nota.")
        return redirect(f"{reverse('evaluacion:registro', args=[a.pk])}?periodo={periodo.pk}")

    notas = {(n.alumno_id, n.competencia_id): n for n in Nota.objects.filter(asignacion=a, periodo=periodo)}
    coms = {c.alumno_id: c.texto for c in Comentario.objects.filter(asignacion=a, periodo=periodo)}
    filas = []
    for al in alumnos:
        valores = []
        for comp in comps:
            n = notas.get((al.pk, comp.pk if comp else None))
            valores.append((comp, n.valor if n else None, n.conclusion if n else ""))
        prom = None
        if config.vigesimal and comps != [None]:
            prom = sv.promedio_vigesimal([v for _, v, _ in valores])
        filas.append({"alumno": al, "valores": valores, "promedio": prom, "comentario": coms.get(al.pk, "")})
    return render(request, "evaluacion/registro.html", {
        "a": a, "anio": anio, "periodo": periodo, "periodos": anio.periodos.all(), "config": config,
        "comps": comps, "filas": filas, "cerrado": cerrado, "letras": LETRAS,
        "cerrado_dir": periodo.notas_cerradas and sv.es_direccion(request.user),
    })


# --- Conducta (tutor) -------------------------------------------------------

@permiso_requerido("notas.registrar", "notas.todas")
def conducta(request, seccion_pk):
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=seccion_pk)
    if not sv.puede_conducta(request.user, seccion):
        raise PermissionDenied
    anio = seccion.anio_lectivo
    periodo = _periodo(request, anio)
    config = ConfigEvaluacion.de(anio, seccion.grado.nivel)
    alumnos = sv.alumnos_periodo(seccion, periodo)
    cerrado = periodo.notas_cerradas and not sv.es_direccion(request.user)
    if request.method == "POST" and not cerrado:
        errores = []
        with transaction.atomic():
            for al in alumnos:
                numero, letra, error = sv.leer_valor(request.POST.get(f"n_{al.pk}"), config)
                if error:
                    errores.append(f"{al.nombres.title()}: {error}")
                    continue
                texto = request.POST.get(f"c_{al.pk}", "").strip()[:600]
                if numero is None and not letra and not texto:
                    Conducta.objects.filter(alumno=al, periodo=periodo).delete()
                else:
                    Conducta.objects.update_or_create(alumno=al, periodo=periodo, defaults={
                        "seccion": seccion, "numero": numero, "letra": letra, "comentario": texto})
        for e in errores[:8]:
            messages.error(request, e)
        if not errores:
            messages.success(request, "Conducta guardada.")
        return redirect(f"{reverse('evaluacion:conducta', args=[seccion.pk])}?periodo={periodo.pk}")
    actuales = {c.alumno_id: c for c in Conducta.objects.filter(periodo=periodo, alumno__in=alumnos)}
    filas = [{"alumno": al, "c": actuales.get(al.pk)} for al in alumnos]
    return render(request, "evaluacion/conducta.html", {
        "seccion": seccion, "anio": anio, "periodo": periodo, "periodos": anio.periodos.all(),
        "config": config, "filas": filas, "cerrado": cerrado, "letras": LETRAS,
    })


# --- Configuración (Dirección) ----------------------------------------------

class ConfigForm(forms.ModelForm):
    class Meta:
        model = ConfigEvaluacion
        fields = ["escala", "por_competencia", "nota_aprobatoria", "comentarios", "conducta"]


@permiso_requerido("notas.configurar")
def configuracion(request):
    anio = AnioLectivo.actual()
    niveles = list(Nivel.objects.filter(grados__secciones__anio_lectivo=anio).distinct()) or list(Nivel.objects.all())
    configs = [ConfigEvaluacion.de(anio, n) for n in niveles]
    forms_ = [ConfigForm(request.POST or None, instance=c, prefix=f"n{c.nivel_id}") for c in configs]
    if request.method == "POST" and request.POST.get("accion") == "config":
        if all(f.is_valid() for f in forms_):
            cambio_escala = []
            for f in forms_:
                if "escala" in f.changed_data and Nota.objects.filter(
                        asignacion__seccion__anio_lectivo=anio, asignacion__seccion__grado__nivel=f.instance.nivel).exists():
                    cambio_escala.append(str(f.instance.nivel))
                f.save()
            messages.success(request, "Configuración de evaluación guardada.")
            if cambio_escala:
                messages.warning(request, f"Cambiaste la escala en {', '.join(cambio_escala)} y ya había notas: revisa que estén en la escala correcta.")
            return redirect("evaluacion:configuracion")
    if request.method == "POST" and request.POST.get("accion") == "periodo":
        p = get_object_or_404(Periodo, pk=entero(request.POST.get("periodo_id")), anio_lectivo=anio)
        p.notas_cerradas = not p.notas_cerradas
        p.save(update_fields=["notas_cerradas"])
        messages.success(request, f"Notas del {p.nombre} {'cerradas' if p.notas_cerradas else 'abiertas'}.")
        return redirect("evaluacion:configuracion")
    return render(request, "evaluacion/configuracion.html", {
        "anio": anio, "pares": list(zip(configs, forms_)), "periodos": anio.periodos.all(),
    })


@permiso_requerido("notas.configurar")
def competencias(request):
    niveles = list(Nivel.objects.all())
    nivel = next((n for n in niveles if str(n.pk) == request.GET.get("nivel", "")), niveles[0] if niveles else None)
    cursos = Curso.objects.filter(nivel=nivel, activo=True).prefetch_related("competencias")
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "agregar":
            curso = get_object_or_404(Curso, pk=entero(request.POST.get("curso")))
            nombre = request.POST.get("nombre", "").strip()
            if nombre:
                Competencia.objects.create(curso=curso, nombre=nombre[:250], orden=curso.competencias.count() + 1)
                messages.success(request, f"Competencia agregada a {curso}.")
        elif accion == "alternar":
            c = get_object_or_404(Competencia, pk=entero(request.POST.get("competencia")))
            c.activo = not c.activo
            c.save(update_fields=["activo"])
        elif accion == "renombrar":
            c = get_object_or_404(Competencia, pk=entero(request.POST.get("competencia")))
            nombre = request.POST.get("nombre", "").strip()
            if nombre:
                c.nombre = nombre[:250]
                c.save(update_fields=["nombre"])
                messages.success(request, "Competencia actualizada.")
        return redirect(f"{reverse('evaluacion:competencias')}?nivel={nivel.pk}")
    return render(request, "evaluacion/competencias.html", {"niveles": niveles, "nivel": nivel, "cursos": cursos})


# --- Avance (Dirección) -----------------------------------------------------

@permiso_requerido("notas.avance")
def avance(request):
    anio = AnioLectivo.actual()
    periodo = _periodo(request, anio)
    asignaciones = list(Asignacion.objects.filter(seccion__anio_lectivo=anio, curso__activo=True).select_related(
        "curso", "seccion__grado__nivel", "docente").order_by(
        "seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre", "curso__orden"))
    av = sv.esperadas_y_registradas(asignaciones, periodo) if periodo else {}
    secciones = {}
    for a in asignaciones:
        a.hechas, a.esperadas = av.get(a.pk, (0, 0))
        a.pct = round(100 * a.hechas / a.esperadas) if a.esperadas else 0
        secciones.setdefault(a.seccion, []).append(a)
    total_h = sum(a.hechas for a in asignaciones)
    total_e = sum(a.esperadas for a in asignaciones)
    pendientes_docente = {}
    for a in asignaciones:
        if a.pct < 100 and a.docente_id:
            pendientes_docente.setdefault(a.docente, []).append(a)
    return render(request, "evaluacion/avance.html", {
        "anio": anio, "periodo": periodo, "periodos": anio.periodos.all(), "secciones": secciones,
        "pct_total": round(100 * total_h / total_e) if total_e else 0,
        "pendientes_docente": sorted(pendientes_docente.items(), key=lambda kv: -len(kv[1])),
    })


# --- Libretas ---------------------------------------------------------------

@requiere_modulo("notas")
def libreta(request, alumno_pk):
    alumno = get_object_or_404(Alumno, pk=alumno_pk)
    anio = AnioLectivo.actual()
    datos = sv.libreta(alumno, anio)
    if datos is None:
        messages.info(request, f"{alumno.nombres} no está matriculado en {anio}.")
        return redirect("alumnos:detalle", pk=alumno.pk)
    if not (puede(request.user, "notas.libretas", "notas.todas") or datos["seccion"].tutor_id == request.user.pk):
        raise PermissionDenied
    return render(request, "evaluacion/libreta.html", {"libretas": [datos], "una": True})


@permiso_requerido("notas.libretas")
def libretas_seccion(request, seccion_pk):
    seccion = get_object_or_404(Seccion.objects.select_related("anio_lectivo"), pk=seccion_pk)
    periodo_hasta = _periodo(request, seccion.anio_lectivo)
    alumnos = sv.alumnos_periodo(seccion, periodo_hasta) if periodo_hasta else []
    libretas = [d for d in (sv.libreta(al, seccion.anio_lectivo) for al in alumnos) if d]
    return render(request, "evaluacion/libreta.html", {"libretas": libretas, "una": False, "seccion": seccion})


# --- Consolidado para el SIAGIE ---------------------------------------------

@permiso_requerido("notas.siagie")
def consolidado_siagie(request, seccion_pk):
    """Excel por sección y periodo: una hoja por curso, en el orden de la nómina,
    para copiar las columnas a la plantilla que se descarga del SIAGIE."""
    from django.http import HttpResponse
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=seccion_pk)
    anio = seccion.anio_lectivo
    periodo = _periodo(request, anio)
    config = ConfigEvaluacion.de(anio, seccion.grado.nivel)
    alumnos = sorted(sv.alumnos_periodo(seccion, periodo),
                     key=lambda a: (a.apellido_paterno, a.apellido_materno, a.nombres))
    wb = Workbook()
    wb.remove(wb.active)
    azul = PatternFill("solid", fgColor="0D6EFD")
    for a in Asignacion.objects.filter(seccion=seccion, curso__activo=True).select_related("curso").order_by("curso__orden"):
        comps = sv.competencias_de(a, config)
        notas_obj = {(n.alumno_id, n.competencia_id): n for n in Nota.objects.filter(asignacion=a, periodo=periodo)}
        notas = {k: n.valor for k, n in notas_obj.items()}
        coms = {c.alumno_id: c.texto for c in Comentario.objects.filter(asignacion=a, periodo=periodo)}
        # conclusión: las de cada competencia (si hay) o el comentario del curso
        for (al_id, comp_id), n in notas_obj.items():
            if n.conclusion:
                previo = coms.get(al_id, "")
                etiqueta = next((f"C{i}" for i, c in enumerate(comps, start=1) if c and c.pk == comp_id), "")
                coms[al_id] = (previo + " " if previo else "") + (f"{etiqueta}: " if etiqueta else "") + n.conclusion
        ws = wb.create_sheet((a.curso.abreviatura or a.curso.nombre)[:31])
        ws["A1"] = f"{a.curso} – {seccion.grado.nombre} «{seccion.nombre}» {seccion.grado.nivel} – {periodo.nombre} {anio}"
        ws["A1"].font = Font(bold=True)
        enc = ["N°", "DNI / código", "Apellidos y nombres"] + [
            (f"C{i}" if c else "Nota") for i, c in enumerate(comps, start=1)] + ["Conclusión descriptiva / comentario"]
        ws.append([])
        ws.append(enc)
        for celda in ws[3]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = azul
            celda.alignment = Alignment(horizontal="center", wrap_text=True)
        for i, al in enumerate(alumnos, start=1):
            ws.append([i, al.codigo or al.numero_documento, f"{al.apellidos}, {al.nombres}"]
                      + [notas.get((al.pk, c.pk if c else None), "") for c in comps] + [coms.get(al.pk, "")])
        fila = ws.max_row + 2
        for i, c in enumerate(comps, start=1):
            if c:
                ws.cell(row=fila, column=1, value=f"C{i}: {c.nombre}").font = Font(italic=True, size=9)
                fila += 1
        anchos = [5, 14, 38] + [7] * len(comps) + [60]
        for i, w in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "D4"
    if not wb.sheetnames:
        wb.create_sheet("Sin cursos")
    nombre = f"consolidado_{seccion.grado.nombre}_{seccion.nombre}_{periodo.nombre}_{anio}.xlsx".replace(" ", "_")
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, nombre)
    return resp


# --- Llenar la plantilla del SIAGIE -----------------------------------------

def _opciones_hoja(hoja, ctx):
    comps = ctx.comps.get(hoja.get("asignacion")) or []
    return [(str(c.pk) if c else "0", f"C{i} – {c.nombre}" if c else "Nota del curso") for i, c in enumerate(comps, start=1)]


@permiso_requerido("notas.siagie")
def siagie_llenar(request):
    import os
    import uuid

    from django.conf import settings

    from . import siagie

    anio = AnioLectivo.actual()
    clave = "siagie_plantilla"
    secciones = Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre")
    accion = request.POST.get("accion")

    if request.method == "POST" and accion == "analizar":
        archivo = request.FILES.get("archivo")
        seccion = Seccion.objects.filter(pk=entero(request.POST.get("seccion")), anio_lectivo=anio).first()
        periodo = Periodo.objects.filter(pk=entero(request.POST.get("periodo")), anio_lectivo=anio).first()
        if not (archivo and seccion and periodo):
            messages.error(request, "Elige la sección, el periodo y el archivo.")
            return redirect("evaluacion:siagie")
        ext = os.path.splitext(archivo.name)[1].lower()
        if archivo.size > 5 * 1024 * 1024:
            messages.error(request, "El archivo es muy grande (máximo 5 MB).")
            return redirect("evaluacion:siagie")
        if ext == ".xls":
            messages.error(request, "El archivo es .xls (formato antiguo de Excel) y no se puede llenar automáticamente. "
                                    "Usa el Excel «Para SIAGIE» de Avance y copia las columnas, o avísame para revisar ese formato.")
            return redirect("evaluacion:siagie")
        if ext not in (".xlsx", ".xlsm"):
            messages.error(request, "El archivo debe ser la plantilla de Excel descargada del SIAGIE (.xlsx).")
            return redirect("evaluacion:siagie")
        analisis, error = siagie.analizar(archivo, seccion, periodo)
        if error:
            messages.error(request, error)
            return redirect("evaluacion:siagie")
        # fuera de MEDIA (nunca se publica); se borran las plantillas de más de un día
        carpeta = os.path.join(settings.ARCHIVOS_PRIVADOS, "siagie")
        os.makedirs(carpeta, exist_ok=True)
        import time

        for viejo in os.listdir(carpeta):
            camino = os.path.join(carpeta, viejo)
            if os.path.isfile(camino) and time.time() - os.path.getmtime(camino) > 86400:
                os.remove(camino)
        ruta = os.path.join(carpeta, f"{uuid.uuid4().hex}{ext}")
        archivo.seek(0)
        with open(ruta, "wb") as f:
            for trozo in archivo.chunks():
                f.write(trozo)
        request.session[clave] = {"ruta": ruta, "nombre": archivo.name, "seccion": seccion.pk, "periodo": periodo.pk, "analisis": analisis}
        return redirect("evaluacion:siagie_revisar")

    return render(request, "evaluacion/siagie_subir.html", {
        "anio": anio, "secciones": secciones, "periodos": anio.periodos.all(),
        "periodo_actual": sv.periodo_actual(anio),
    })


@permiso_requerido("notas.siagie")
def siagie_revisar(request):
    import os

    from django.http import HttpResponse

    from . import siagie

    datos = request.session.get("siagie_plantilla")
    if not datos or not os.path.exists(datos["ruta"]):
        messages.info(request, "Sube la plantilla del SIAGIE para empezar.")
        return redirect("evaluacion:siagie")
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=datos["seccion"])
    periodo = get_object_or_404(Periodo, pk=datos["periodo"])
    ctx = siagie.Contexto(seccion, periodo)
    analisis = datos["analisis"]
    nombres = {a.pk: f"{a.apellidos}, {a.nombres}" for a in ctx.alumnos}

    if request.method == "POST":
        # aplicar lo que el usuario corrigió
        for i, h in enumerate(analisis["hojas"]):
            nueva = request.POST.get(f"hoja_{i}", "")
            nueva = int(nueva) if nueva.isdigit() else None
            if nueva != h.get("asignacion"):
                h["asignacion"] = nueva
                siagie.mapear_columnas(h, ctx)
            else:
                for col in h["columnas"]:
                    v = request.POST.get(f"col_{i}_{col['col']}", None)
                    if v is None:
                        continue
                    col["competencia"] = v if v == "todas" else (int(v) if v.isdigit() else None)
        datos["analisis"] = analisis
        request.session["siagie_plantilla"] = datos
        if request.POST.get("accion") == "llenar":
            contenido, escritas, omitidas = siagie.llenar(
                datos["ruta"], datos["nombre"], analisis, seccion, periodo, sobrescribir=request.POST.get("sobrescribir") == "on")
            ctype = ("application/vnd.ms-excel.sheet.macroEnabled.12" if datos["nombre"].lower().endswith(".xlsm")
                     else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp = HttpResponse(contenido, content_type=ctype)
            resp["Content-Disposition"] = content_disposition_header(True, datos["nombre"])
            resp["X-Celdas-Escritas"] = str(escritas)
            return resp
        return redirect("evaluacion:siagie_revisar")

    hojas = []
    for i, h in enumerate(analisis["hojas"]):
        opciones = _opciones_hoja(h, ctx)
        hojas.append({
            "i": i, "h": h, "opciones": opciones,
            "alumnos": [(fila, nombres.get(a, "?")) for fila, a in h["filas"]],
            "notas": [c for c in h["columnas"] if c["tipo"] == "nota"],
            "conclusiones": [c for c in h["columnas"] if c["tipo"] == "conclusion"],
        })
    return render(request, "evaluacion/siagie_revisar.html", {
        "seccion": seccion, "periodo": periodo, "nombre": datos["nombre"], "hojas": hojas,
        "faltan": analisis["faltan"], "asignaciones": ctx.asignaciones,
    })
