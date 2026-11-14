"""Pantallas de la Programación del año."""
from datetime import time

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms import FECHA
from core.models import AnioLectivo, DiaNoLectivo, Grado, Nivel, Seccion
from core.utils import entero
from core.permisos import permiso_requerido, puede, requiere_modulo

from . import programacion as prog
from .models import DIAS_SEMANA, Asignacion, Bloque, Clase, Curso, HorasPlan

User = get_user_model()


def _anio(request):
    pk = request.GET.get("anio") or request.POST.get("anio")
    if pk and str(pk).isdigit():
        a = AnioLectivo.objects.filter(pk=pk).first()
        if a:
            return a
    return AnioLectivo.actual()


def _url(nombre, anio, **extra):
    q = f"?anio={anio.pk}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return reverse(nombre) + q


# --- Panel ------------------------------------------------------------------

@permiso_requerido("programacion.editar")
def panel(request):
    anio = _anio(request)
    if anio is None:
        messages.info(request, "Empieza creando el año lectivo.")
        return redirect("core:anio_nuevo")
    e = prog.estado(anio)
    pasos = [
        {"n": 1, "titulo": "Calendario", "icono": "bi-calendar3", "url": _url("academico:calendario", anio),
         "ok": e["periodos"] > 0 and e["no_lectivos"] > 0,
         "detalle": f"{e['periodos']} periodos · {e['no_lectivos']} feriados/vacaciones · {e['dias_lectivos']} días de clase",
         "ayuda": "Fechas del año, bimestres o trimestres, feriados y vacaciones."},
        {"n": 2, "titulo": "Grados y secciones", "icono": "bi-grid-3x3-gap", "url": reverse("core:anio_detalle", args=[anio.pk]),
         "ok": e["secciones"] > 0,
         "detalle": f"{e['secciones']} secciones",
         "ayuda": "Qué secciones hay (1ro A, 1ro B…), vacantes y turno."},
        {"n": 3, "titulo": "Plan de estudios", "icono": "bi-journal-text", "url": _url("academico:plan", anio),
         "ok": e["grados"] > 0 and e["plan_grados"] >= e["grados"],
         "detalle": f"{e['plan_grados']} de {e['grados']} grados con horas definidas",
         "ayuda": "Qué cursos lleva cada grado y cuántas horas a la semana."},
        {"n": 4, "titulo": "Tutores y docentes", "icono": "bi-person-badge", "url": reverse("academico:docentes"),
         "ok": e["asignaciones"] > 0 and e["sin_docente"] == 0 and e["sin_tutor"] == 0 and e["secciones_sin_cursos"] == 0,
         "detalle": (f"{e['asignaciones']} cursos asignados" +
                     (f" · {e['sin_docente']} sin docente" if e["sin_docente"] else "") +
                     (f" · {e['sin_tutor']} secciones sin tutor" if e["sin_tutor"] else "")),
         "ayuda": "Quién es tutor de cada sección y quién dicta cada curso."},
        {"n": 5, "titulo": "Jornada (horas y recreos)", "icono": "bi-clock", "url": _url("academico:jornada", anio),
         "ok": e["niveles"] > 0 and e["jornadas"] >= e["niveles"],
         "detalle": f"{e['jornadas']} de {e['niveles']} niveles con jornada",
         "ayuda": "A qué hora empieza cada hora de clase y los recreos."},
        {"n": 6, "titulo": "Horario de clases", "icono": "bi-table", "url": _url("academico:horarios", anio),
         "ok": e["horas_necesarias"] > 0 and e["clases"] >= e["horas_necesarias"] and e["cruces"] == 0,
         "detalle": (f"{e['clases']} de {e['horas_necesarias']} horas ubicadas" +
                     (f" · {e['cruces']} cruce{'s' if e['cruces'] != 1 else ''}" if e["cruces"] else "")),
         "alerta": e["cruces"] > 0,
         "ayuda": "Arma el horario semanal de cada sección. Avisa si un docente queda en dos aulas a la vez."},
    ]
    hechos = sum(1 for p in pasos if p["ok"])
    problemas_carga = [f for f in prog.control_carga(anio) if f["problemas"]]
    from alumnos.models import Matricula

    # Si el año aún no tiene alumnos pero el anterior sí: sugerir el pase de año
    anterior = AnioLectivo.objects.filter(anio__lt=anio.anio).order_by("-anio").first()
    pendiente_pase = bool(
        anterior and e["secciones"] and not Matricula.objects.filter(anio_lectivo=anio).exists()
        and Matricula.objects.filter(anio_lectivo=anterior, estado=Matricula.Estado.MATRICULADO).exists()
    )
    otros = AnioLectivo.objects.exclude(pk=anio.pk)
    return render(request, "academico/prog/panel.html", {
        "anio": anio, "anios": AnioLectivo.objects.all(), "pasos": pasos, "hechos": hechos,
        "porcentaje": round(100 * hechos / len(pasos)), "otros": otros,
        "pendiente_pase": pendiente_pase, "anterior": anterior, "problemas_carga": problemas_carga,
    })


# --- 1. Calendario ----------------------------------------------------------

class DiaNoLectivoForm(forms.ModelForm):
    class Meta:
        model = DiaNoLectivo
        fields = ["tipo", "motivo", "fecha", "fecha_fin"]
        widgets = {"fecha": FECHA, "fecha_fin": FECHA}


@permiso_requerido("programacion.editar")
def calendario(request):
    anio = _anio(request)
    form = DiaNoLectivoForm(request.POST or None, initial={"tipo": DiaNoLectivo.Tipo.VACACIONES})
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "feriados":
            n = prog.cargar_feriados(anio)
            messages.success(request, f"Se agregaron {n} feriados nacionales que caen de lunes a viernes." if n else "Los feriados nacionales ya estaban cargados.")
            return redirect(_url("academico:calendario", anio))
        if accion == "agregar" and form.is_valid():
            d = form.save(commit=False)
            d.anio_lectivo = anio
            d.save()
            messages.success(request, f"«{d.motivo}» agregado.")
            return redirect(_url("academico:calendario", anio))
    dias = list(anio.dias_no_lectivos.all())
    periodos = list(anio.periodos.all())
    for p in periodos:
        p.lectivos = len(prog.dias_lectivos(anio, p.fecha_inicio, p.fecha_fin))
    return render(request, "academico/prog/calendario.html", {
        "anio": anio, "form": form, "dias": dias, "periodos": periodos,
        "total_lectivos": len(prog.dias_lectivos(anio)),
    })


@permiso_requerido("programacion.editar")
@require_POST
def calendario_eliminar(request, pk):
    d = get_object_or_404(DiaNoLectivo, pk=pk)
    anio = d.anio_lectivo
    d.delete()
    messages.success(request, f"«{d.motivo}» eliminado.")
    return redirect(_url("academico:calendario", anio))


# --- 3. Plan de estudios ----------------------------------------------------

@permiso_requerido("programacion.editar")
def plan(request):
    anio = _anio(request)
    niveles = list(Nivel.objects.filter(grados__secciones__anio_lectivo=anio).distinct()) or list(Nivel.objects.all())
    nivel = next((n for n in niveles if str(n.pk) == request.GET.get("nivel", "")), niveles[0] if niveles else None)
    if nivel is None:
        return redirect(_url("academico:panel", anio))
    grados = list(Grado.objects.filter(nivel=nivel, secciones__anio_lectivo=anio).distinct()) or list(nivel.grados.all())
    cursos = list(Curso.objects.filter(nivel=nivel, activo=True))
    actuales = prog.horas_plan(anio)

    if request.method == "POST":
        sugeridas = request.POST.get("accion") == "sugeridas"
        tabla = prog.HORAS_SUGERIDAS.get(nivel.nombre, {})
        with transaction.atomic():
            for g in grados:
                for c in cursos:
                    if sugeridas:
                        if (g.pk, c.pk) in actuales:
                            continue
                        horas = tabla.get(c.abreviatura, 0)
                    else:
                        v = request.POST.get(f"h_{g.pk}_{c.pk}", "0").strip() or "0"
                        horas = int(v) if v.isdigit() else 0
                    HorasPlan.objects.update_or_create(anio_lectivo=anio, grado=g, curso=c, defaults={"horas": min(horas, 20)})
        messages.success(request, "Se cargaron las horas sugeridas (revísalas y ajústalas)." if sugeridas else f"Plan de estudios de {nivel} guardado.")
        return redirect(_url("academico:plan", anio, nivel=nivel.pk))

    filas = [{"curso": c, "celdas": [(g, actuales.get((g.pk, c.pk), "")) for g in grados]} for c in cursos]
    totales = [sum(actuales.get((g.pk, c.pk), 0) or 0 for c in cursos) for g in grados]
    return render(request, "academico/prog/plan.html", {
        "anio": anio, "niveles": niveles, "nivel": nivel, "grados": grados, "filas": filas, "totales": totales,
        "vacio": not any(actuales.get((g.pk, c.pk)) for g in grados for c in cursos),
        "hay_sugeridas": nivel.nombre in prog.HORAS_SUGERIDAS,
    })


# --- 5. Jornada -------------------------------------------------------------

class GenerarJornadaForm(forms.Form):
    inicio = forms.TimeField(label="Hora de entrada", initial=time(8, 0), widget=forms.TimeInput(attrs={"type": "time"}))
    duracion = forms.IntegerField(label="Minutos por hora", min_value=20, max_value=120, initial=45)
    n_horas = forms.IntegerField(label="Horas de clase al día", min_value=1, max_value=12, initial=7)
    recreo1_tras = forms.IntegerField(label="1er recreo después de la hora", min_value=0, max_value=12, initial=3, required=False)
    recreo1_min = forms.IntegerField(label="Minutos", min_value=0, max_value=90, initial=20, required=False)
    recreo2_tras = forms.IntegerField(label="2do recreo después de la hora", min_value=0, max_value=12, initial=5, required=False)
    recreo2_min = forms.IntegerField(label="Minutos", min_value=0, max_value=90, initial=10, required=False)


@permiso_requerido("programacion.editar")
def jornada(request):
    anio = _anio(request)
    niveles = list(Nivel.objects.filter(grados__secciones__anio_lectivo=anio).distinct()) or list(Nivel.objects.all())
    nivel = next((n for n in niveles if str(n.pk) == request.GET.get("nivel", "")), niveles[0] if niveles else None)
    if nivel is None:
        return redirect(_url("academico:panel", anio))
    bloques = list(Bloque.objects.filter(anio_lectivo=anio, nivel=nivel))
    n = 0
    for b in bloques:
        if not b.es_recreo:
            n += 1
            b.numero = n
    inicial = {}
    clases_b = [b for b in bloques if not b.es_recreo]
    if clases_b:  # el formulario muestra la jornada actual
        recreos = [(sum(1 for c in clases_b if c.orden < r.orden), r.minutos) for r in bloques if r.es_recreo]
        inicial = {"inicio": clases_b[0].inicio, "duracion": clases_b[0].minutos, "n_horas": len(clases_b),
                   "recreo1_tras": recreos[0][0] if recreos else None, "recreo1_min": recreos[0][1] if recreos else None,
                   "recreo2_tras": recreos[1][0] if len(recreos) > 1 else None, "recreo2_min": recreos[1][1] if len(recreos) > 1 else None}
    form = GenerarJornadaForm(request.POST if request.POST.get("accion") == "generar" else None, initial=inicial)
    accion = request.POST.get("accion")

    if request.method == "POST" and accion == "generar" and form.is_valid():
        d = form.cleaned_data
        recreos = [(d[f"recreo{i}_tras"], d[f"recreo{i}_min"]) for i in (1, 2) if d.get(f"recreo{i}_tras") and d.get(f"recreo{i}_min")]
        try:
            prog.generar_bloques(anio, nivel, d["inicio"], d["duracion"], d["n_horas"], recreos)
            messages.success(request, f"Jornada de {nivel} creada.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect(_url("academico:jornada", anio, nivel=nivel.pk))

    if request.method == "POST" and accion == "guardar":
        errores = []
        with transaction.atomic():
            for b in bloques:
                try:
                    ini = time.fromisoformat(request.POST.get(f"i_{b.pk}", ""))
                    fin = time.fromisoformat(request.POST.get(f"f_{b.pk}", ""))
                except ValueError:
                    errores.append(b)
                    continue
                if fin <= ini:
                    errores.append(b)
                    continue
                b.inicio, b.fin = ini, fin
                b.save(update_fields=["inicio", "fin"])
        if errores:
            messages.error(request, "Algunas horas no eran válidas (la hora de fin debe ser mayor que la de inicio).")
        else:
            messages.success(request, "Horas actualizadas.")
        return redirect(_url("academico:jornada", anio, nivel=nivel.pk))

    if request.method == "POST" and accion == "copiar":
        origen = next((n for n in niveles if str(n.pk) == request.POST.get("desde")), None)
        if origen and origen != nivel:
            if Clase.objects.filter(bloque__anio_lectivo=anio, bloque__nivel=nivel).exists():
                messages.error(request, "Esta jornada ya se usa en horarios; no se puede reemplazar.")
            else:
                with transaction.atomic():
                    Bloque.objects.filter(anio_lectivo=anio, nivel=nivel).delete()
                    for b in Bloque.objects.filter(anio_lectivo=anio, nivel=origen):
                        Bloque.objects.create(anio_lectivo=anio, nivel=nivel, orden=b.orden, inicio=b.inicio, fin=b.fin, tipo=b.tipo)
                messages.success(request, f"Se copió la jornada de {origen} a {nivel}.")
        return redirect(_url("academico:jornada", anio, nivel=nivel.pk))

    usada = Clase.objects.filter(bloque__anio_lectivo=anio, bloque__nivel=nivel).exists()
    con_jornada = set(Bloque.objects.filter(anio_lectivo=anio).values_list("nivel_id", flat=True))
    return render(request, "academico/prog/jornada.html", {
        "anio": anio, "niveles": niveles, "nivel": nivel, "bloques": bloques, "form": form, "usada": usada,
        "copiables": [n for n in niveles if n.pk in con_jornada and n.pk != nivel.pk],
        "n_clases": sum(1 for b in bloques if not b.es_recreo),
        "hasta": bloques[-1].fin if bloques else None,
    })


# --- 6. Horario -------------------------------------------------------------

@permiso_requerido("programacion.horarios", "programacion.editar")
def horarios(request):
    anio = _anio(request)
    hp = prog.horas_plan(anio)
    secciones = list(Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre"))
    ubicadas = {}
    for c in Clase.objects.filter(seccion__in=secciones).values_list("seccion_id", flat=True):
        ubicadas[c] = ubicadas.get(c, 0) + 1
    necesarias = {}
    for a in Asignacion.objects.filter(seccion__in=secciones).select_related("seccion"):
        necesarias[a.seccion_id] = necesarias.get(a.seccion_id, 0) + hp.get((a.seccion.grado_id, a.curso_id), 0)
    for s in secciones:
        s.ubicadas = ubicadas.get(s.pk, 0)
        s.necesarias = necesarias.get(s.pk, 0)
        s.pct = min(100, round(100 * s.ubicadas / s.necesarias)) if s.necesarias else 0
    carga = prog.resumen_carga(anio)
    docentes = User.objects.filter(pk__in=carga.keys()).order_by("first_name", "last_name")
    for d in docentes:
        d.carga = carga[d.pk]
    return render(request, "academico/prog/horarios.html", {
        "anio": anio, "secciones": secciones, "docentes": docentes, "cruces": prog.cruces_del_anio(anio),
        "jornadas": set(Bloque.objects.filter(anio_lectivo=anio).values_list("nivel_id", flat=True)),
    })


def _contexto_horario(seccion, celda_error=None):
    anio = seccion.anio_lectivo
    bloques = list(Bloque.objects.filter(anio_lectivo=anio, nivel=seccion.grado.nivel))
    asignaciones = list(seccion.asignaciones.select_related("curso", "docente").order_by("curso__orden"))
    hp = prog.horas_plan(anio)
    clases = {(c.dia, c.bloque_id): c for c in seccion.clases.select_related("asignacion__curso", "asignacion__docente")}
    docentes = [a.docente_id for a in asignaciones if a.docente_id]
    ocup = prog.ocupacion_docentes(anio, docentes, excluir_seccion=seccion)
    usadas = {}
    for c in clases.values():
        usadas[c.asignacion_id] = usadas.get(c.asignacion_id, 0) + 1
    for i, a in enumerate(asignaciones):
        a.color = f"hsl({(i * 47) % 360}, 70%, 87%)"
        a.plan = hp.get((seccion.grado_id, a.curso_id), 0)
        a.usadas = usadas.get(a.pk, 0)
        a.faltan = max(a.plan - a.usadas, 0)
    filas = []
    for b in bloques:
        celdas = []
        for d, _ in DIAS_SEMANA:
            c = clases.get((d, b.pk))
            choque = prog.cruce(ocup, c.asignacion.docente_id, d, b) if c and c.asignacion.docente_id else None
            opciones = []
            if not b.es_recreo:
                for a in asignaciones:
                    ocupado = prog.cruce(ocup, a.docente_id, d, b) if a.docente_id else None
                    opciones.append({"a": a, "ocupado": ocupado})
            celdas.append({"dia": d, "clase": c, "choque": choque, "opciones": opciones,
                           "error": celda_error if celda_error and celda_error[:2] == (d, b.pk) else None})
        filas.append({"bloque": b, "celdas": celdas})
    total_plan = sum(a.plan for a in asignaciones)
    return {
        "seccion": seccion, "anio": anio, "bloques": bloques, "filas": filas, "dias": DIAS_SEMANA,
        "asignaciones": asignaciones, "total_plan": total_plan, "total_usadas": len(clases),
        "n_choques": sum(1 for f in filas for c in f["celdas"] if c["choque"]),
        "capacidad": 5 * sum(1 for b in bloques if not b.es_recreo),
    }


@permiso_requerido("programacion.horarios", "programacion.editar")
def horario_seccion(request, seccion_pk):
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=seccion_pk)
    ctx = _contexto_horario(seccion)
    lista = list(Seccion.objects.filter(anio_lectivo=seccion.anio_lectivo).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre"))
    i = next((k for k, s in enumerate(lista) if s.pk == seccion.pk), 0)
    ctx.update({"todas": lista, "anterior": lista[i - 1] if i > 0 else None, "siguiente": lista[i + 1] if i + 1 < len(lista) else None})
    return render(request, "academico/prog/horario_seccion.html", ctx)


@permiso_requerido("programacion.editar")
@require_POST
def horario_celda(request, seccion_pk):
    """HTMX: pone o quita un curso en una celda y devuelve el horario actualizado."""
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo"), pk=seccion_pk)
    dia = entero(request.POST.get("dia")) or 0
    bloque = get_object_or_404(Bloque, pk=entero(request.POST.get("bloque")), anio_lectivo=seccion.anio_lectivo, nivel=seccion.grado.nivel)
    asig_id = entero(request.POST.get("asignacion"))
    error = None
    if dia not in dict(DIAS_SEMANA) or bloque.es_recreo:
        error = "Celda no válida."
    elif not asig_id:
        Clase.objects.filter(seccion=seccion, dia=dia, bloque=bloque).delete()
    else:
        a = get_object_or_404(Asignacion, pk=asig_id, seccion=seccion)
        Clase.objects.update_or_create(seccion=seccion, dia=dia, bloque=bloque, defaults={"asignacion": a})
    ctx = _contexto_horario(seccion, (dia, bloque.pk, error) if error else None)
    return render(request, "academico/prog/partials/horario_grid.html", ctx)


@permiso_requerido("programacion.editar")
@require_POST
def horario_vaciar(request, seccion_pk):
    seccion = get_object_or_404(Seccion, pk=seccion_pk)
    n = seccion.clases.count()
    seccion.clases.all().delete()
    messages.success(request, f"Se vació el horario ({n} horas).")
    return redirect("academico:horario_seccion", seccion_pk=seccion.pk)


def horario_de_docente(docente, anio):
    clases = list(Clase.objects.filter(seccion__anio_lectivo=anio, asignacion__docente=docente).select_related(
        "bloque", "seccion__grado__nivel", "asignacion__curso"))
    # filas: horas distintas (inicio-fin) ordenadas, columnas: días
    franjas = sorted({(c.bloque.inicio, c.bloque.fin) for c in clases})
    celdas = {}
    for c in clases:
        celdas.setdefault((c.dia, c.bloque.inicio, c.bloque.fin), []).append(c)
    filas = [{"inicio": i, "fin": f, "celdas": [celdas.get((d, i, f), []) for d, _ in DIAS_SEMANA]} for i, f in franjas]
    minutos = sum(c.bloque.minutos for c in clases)
    return {"filas": filas, "n": len(clases), "horas_reloj": round(minutos / 60, 1)}


@requiere_modulo("programacion")
def horario_docente(request, user_pk):
    if user_pk != request.user.pk and not puede(request.user, "programacion.horarios", "programacion.editar"):
        raise PermissionDenied
    docente = get_object_or_404(User, pk=user_pk)
    anio = _anio(request)
    ctx = horario_de_docente(docente, anio)
    ctx.update({"docente": docente, "anio": anio, "dias": DIAS_SEMANA})
    return render(request, "academico/prog/horario_docente.html", ctx)


# --- Copiar -----------------------------------------------------------------

@permiso_requerido("programacion.editar")
def copiar(request):
    anios = list(AnioLectivo.objects.order_by("-anio"))
    destino = _anio(request)
    previos = [a for a in anios if a.anio < destino.anio] if destino else []
    origen_id = request.POST.get("origen") or request.GET.get("origen")
    origen = next((a for a in anios if str(a.pk) == str(origen_id)), previos[0] if previos else None)
    opciones = [
        ("periodos", "Bimestres / trimestres", "Con las mismas fechas, un año después."),
        ("calendario", "Vacaciones y feriados", "Las vacaciones se copian; los feriados se recalculan para el nuevo año."),
        ("secciones", "Grados y secciones", "Mismas letras, vacantes, turno y tutor."),
        ("plan", "Plan de estudios", "Horas semanales de cada curso por grado."),
        ("docentes", "Docentes por curso", "Quién dicta cada curso en cada sección."),
        ("jornada", "Jornada", "Horas de entrada, horas de clase y recreos."),
        ("horario", "Horario de clases", "El horario semanal completo de cada sección."),
    ]
    if request.method == "POST" and origen and destino and origen != destino:
        que = set(request.POST.getlist("que"))
        if not que:
            messages.error(request, "Marca al menos una parte a copiar.")
        else:
            r = prog.copiar(origen, destino, que)
            hecho = ", ".join(f"{v} {k}" for k, v in r.items() if v) or "nada nuevo (ya estaba todo)"
            messages.success(request, f"Programación copiada de {origen} a {destino}: {hecho}.")
            return redirect(_url("academico:panel", destino))
    return render(request, "academico/prog/copiar.html", {
        "anios": anios, "origen": origen, "destino": destino, "opciones": opciones,
    })


@permiso_requerido("programacion.editar")
def carga(request):
    anio = _anio(request)
    filas = prog.control_carga(anio)
    return render(request, "academico/prog/carga.html", {
        "anio": anio, "filas": filas,
        "n_problemas": sum(1 for f in filas if f["problemas"]),
        "dias": DIAS_SEMANA,
    })
