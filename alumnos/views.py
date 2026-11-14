from django.contrib import messages
from django.utils.http import content_disposition_header
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import AnioLectivo
from core.permisos import permiso_requerido

from . import excel
from .utils import opciones_en
from .forms import (
    AlumnoForm,
    ApoderadoForm,
    EditarVinculoForm,
    ImportarForm,
    MatriculaForm,
    VinculoApoderadoForm,
)
from .models import Alumno, AlumnoApoderado, Apoderado, Matricula



def _anio(request):
    """Año elegido en ?anio=, o el año en curso."""
    pk = request.GET.get("anio")
    if pk and pk.isdigit():
        anio = AnioLectivo.objects.filter(pk=pk).first()
        if anio:
            return anio
    return AnioLectivo.actual()


def _filtrar(request, anio):
    q = request.GET.get("q", "").strip()
    en = request.GET.get("en", "")  # n<id> = nivel, g<id> = grado, s<id> = sección
    tipo_en, id_en = (en[:1], en[1:]) if len(en) > 1 and en[1:].isdigit() else ("", "")
    estado = request.GET.get("estado", "MAT")

    mats = Matricula.objects.filter(anio_lectivo=anio).select_related("seccion__grado__nivel")
    alumnos = Alumno.objects.prefetch_related(
        Prefetch("matriculas", queryset=mats, to_attr="mats_anio"),
        Prefetch("vinculos", queryset=AlumnoApoderado.objects.select_related("apoderado")),
    )
    if q:
        for palabra in q.split():
            alumnos = alumnos.filter(
                Q(numero_documento__icontains=palabra)
                | Q(apellido_paterno__icontains=palabra)
                | Q(apellido_materno__icontains=palabra)
                | Q(nombres__icontains=palabra)
                | Q(codigo__icontains=palabra)
            )
    filtro_mat = Q(matriculas__anio_lectivo=anio)
    if tipo_en == "s":
        filtro_mat &= Q(matriculas__seccion_id=id_en)
    elif tipo_en == "g":
        filtro_mat &= Q(matriculas__seccion__grado_id=id_en)
    elif tipo_en == "n":
        filtro_mat &= Q(matriculas__seccion__grado__nivel_id=id_en)

    if estado == "SIN":
        alumnos = alumnos.exclude(matriculas__anio_lectivo=anio)
    elif estado in ("MAT", "RET", "TRA"):
        alumnos = alumnos.filter(filtro_mat, matriculas__estado=estado)
    else:  # todos los del año
        alumnos = alumnos.filter(filtro_mat)
    alumnos = alumnos.distinct()
    filtros = {"q": q, "en": en, "estado": estado}
    return alumnos, filtros


def _adjuntar_matricula(alumnos):
    for a in alumnos:
        a.mat = a.mats_anio[0] if a.mats_anio else None
        vs = sorted(a.vinculos.all(), key=lambda v: (not v.responsable_pago, v.id))
        a.apo = vs[0].apoderado if vs else None
    return alumnos


@permiso_requerido("alumnos.ver")
def lista(request):
    anio = _anio(request)
    if anio is None:
        messages.warning(request, "Primero crea el año lectivo en Configuración.")
        return redirect("core:inicio")
    alumnos, filtros = _filtrar(request, anio)
    pagina = Paginator(alumnos, 25).get_page(request.GET.get("page"))
    _adjuntar_matricula(pagina.object_list)

    contexto = {
        "anio": anio,
        "anios": AnioLectivo.objects.all(),
        "pagina": pagina,
        "f": filtros,
        "total": pagina.paginator.count,
        "query": request.GET.copy(),
    }
    contexto["query"].pop("page", None)
    if request.htmx:
        return render(request, "alumnos/partials/tabla.html", contexto)

    contexto["opciones_en"] = opciones_en(anio)
    return render(request, "alumnos/lista.html", contexto)


@permiso_requerido("alumnos.ver")
def exportar(request):
    anio = _anio(request)
    alumnos, _ = _filtrar(request, anio)
    alumnos = _adjuntar_matricula(list(alumnos))
    contenido = excel.exportar(alumnos, anio)
    resp = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"alumnos_{anio}_{timezone.localdate():%Y%m%d}.xlsx")
    return resp


@permiso_requerido("alumnos.ver")
def detalle(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    anio = AnioLectivo.actual()
    contexto = {
        "alumno": alumno,
        "anio": anio,
        "mat_actual": alumno.matricula_en(anio),
        "matriculas": alumno.matriculas.select_related("anio_lectivo", "seccion__grado__nivel"),
        "vinculos": alumno.vinculos.select_related("apoderado").order_by("-responsable_pago", "id"),
    }
    if anio:
        from cobranza.servicios import resumen_alumno

        contexto["cuenta"] = resumen_alumno(alumno, anio)
        from asistencia.servicios import resumen_alumno as resumen_asistencia

        contexto["asist"] = resumen_asistencia(alumno, anio)
    # hermanos: otros alumnos que comparten algún apoderado
    contexto["hermanos"] = (
        Alumno.objects.filter(vinculos__apoderado__in=alumno.apoderados.all()).exclude(pk=alumno.pk).distinct()
    )
    return render(request, "alumnos/detalle.html", contexto)


@permiso_requerido("alumnos.editar")
def nuevo(request):
    anio = AnioLectivo.actual()
    if anio is None:
        messages.warning(request, "Primero crea el año lectivo en Configuración.")
        return redirect("core:anio_nuevo")
    datos = request.POST or None
    archivos = request.FILES or None
    form = AlumnoForm(datos, archivos, prefix="al")
    form_mat = MatriculaForm(datos, prefix="mat", anio=anio)
    campos_apo = ("numero_documento", "apellidos", "nombres", "celular", "email")
    con_apoderado = request.method != "POST" or any(request.POST.get(f"apo-{c}", "").strip() for c in campos_apo)
    form_apo = VinculoApoderadoForm(datos if con_apoderado else None, prefix="apo")

    if request.method == "POST":
        validos = form.is_valid() & form_mat.is_valid() & (form_apo.is_valid() if con_apoderado else True)
        if validos:
            with transaction.atomic():
                alumno = form.save()
                mat = form_mat.save(commit=False)
                mat.alumno = alumno
                mat.anio_lectivo = anio
                mat.save()
                if con_apoderado:
                    form_apo.guardar(alumno)
            messages.success(request, f"Alumno {alumno.nombre_completo} registrado y matriculado en {mat.seccion.grado.nombre} «{mat.seccion.nombre}».")
            if "otro" in request.POST:
                return redirect("alumnos:nuevo")
            return redirect("alumnos:detalle", pk=alumno.pk)

    return render(request, "alumnos/nuevo.html", {"form": form, "form_mat": form_mat, "form_apo": form_apo, "anio": anio})


@permiso_requerido("alumnos.editar")
def editar(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    form = AlumnoForm(request.POST or None, request.FILES or None, instance=alumno)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Datos del alumno actualizados.")
        return redirect("alumnos:detalle", pk=alumno.pk)
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "titulo": "Editar alumno",
            "subtitulo": alumno.nombre_completo,
            "cancelar": reverse("alumnos:detalle", args=[alumno.pk]),
            "breadcrumb": [("Alumnos", reverse("alumnos:lista")), (alumno.apellidos, reverse("alumnos:detalle", args=[alumno.pk]))],
            "multipart": True,
        },
    )


# --- Matrícula --------------------------------------------------------------

@permiso_requerido("alumnos.editar")
def matricular(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    anio = _anio(request)
    if alumno.matricula_en(anio):
        messages.info(request, f"{alumno.nombres} ya está matriculado en {anio}.")
        return redirect("alumnos:detalle", pk=alumno.pk)
    anterior = alumno.matriculas.exclude(anio_lectivo=anio).first()
    form = MatriculaForm(
        request.POST or None, anio=anio,
        initial={"tipo": Matricula.Tipo.RATIFICACION if anterior else Matricula.Tipo.NUEVO},
    )
    if request.method == "POST" and form.is_valid():
        mat = form.save(commit=False)
        mat.alumno = alumno
        mat.anio_lectivo = anio
        mat.save()
        messages.success(request, f"Matriculado en {mat.seccion.grado.nombre} «{mat.seccion.nombre}» ({anio}).")
        return redirect("alumnos:detalle", pk=alumno.pk)
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "titulo": f"Matricular en {anio}",
            "subtitulo": alumno.nombre_completo,
            "cancelar": reverse("alumnos:detalle", args=[alumno.pk]),
            "breadcrumb": [("Alumnos", reverse("alumnos:lista")), (alumno.apellidos, reverse("alumnos:detalle", args=[alumno.pk]))],
        },
    )


@permiso_requerido("alumnos.editar")
def matricula_editar(request, pk):
    mat = get_object_or_404(Matricula.objects.select_related("alumno", "anio_lectivo"), pk=pk)
    form = MatriculaForm(request.POST or None, instance=mat)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Matrícula actualizada.")
        return redirect("alumnos:detalle", pk=mat.alumno_id)
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "titulo": f"Matrícula {mat.anio_lectivo}",
            "subtitulo": mat.alumno.nombre_completo,
            "cancelar": reverse("alumnos:detalle", args=[mat.alumno_id]),
            "breadcrumb": [("Alumnos", reverse("alumnos:lista")), (mat.alumno.apellidos, reverse("alumnos:detalle", args=[mat.alumno_id]))],
            "ayuda": "Para un retiro o traslado cambia el estado: el alumno deja de contar en la sección y se libera la vacante.",
        },
    )


# --- Apoderados -------------------------------------------------------------

@permiso_requerido("alumnos.editar")
def apoderado_agregar(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    form = VinculoApoderadoForm(
        request.POST or None, alumno=alumno, initial={"responsable_pago": not alumno.vinculos.exists()}
    )
    if request.method == "POST" and form.is_valid():
        v = form.guardar(alumno)
        messages.success(request, f"{v.apoderado.nombre_completo} agregado como apoderado.")
        return redirect(reverse("alumnos:detalle", args=[alumno.pk]) + "#apoderados")
    return render(request, "alumnos/apoderado_form.html", {"form": form, "alumno": alumno})


@permiso_requerido("alumnos.editar")
def apoderado_buscar(request):
    """HTMX: al escribir el DNI, si el apoderado ya existe se completan sus datos."""
    prefijo = request.GET.get("prefix", "")
    clave = f"{prefijo}-numero_documento" if prefijo else "numero_documento"
    numero = request.GET.get(clave, "").strip().upper()
    apo = Apoderado.objects.filter(numero_documento=numero).prefetch_related("alumnos").first() if numero else None
    datos = request.GET.copy()
    if apo:
        for campo in ("tipo_documento", "apellidos", "nombres", "celular", "email"):
            datos[f"{prefijo}-{campo}" if prefijo else campo] = getattr(apo, campo)
    form = VinculoApoderadoForm(prefix=prefijo or None, initial={k.split("-", 1)[-1]: v for k, v in datos.items()})
    return render(request, "alumnos/partials/apoderado_campos.html", {"form_apo": form, "encontrado": apo, "prefijo": prefijo})


@permiso_requerido("alumnos.editar")
def vinculo_editar(request, pk):
    v = get_object_or_404(AlumnoApoderado.objects.select_related("alumno", "apoderado"), pk=pk)
    form_apo = ApoderadoForm(request.POST or None, instance=v.apoderado, prefix="apo")
    form_v = EditarVinculoForm(request.POST or None, instance=v, prefix="v")
    if request.method == "POST" and form_apo.is_valid() and form_v.is_valid():
        form_apo.save()
        form_v.save()
        messages.success(request, "Datos del apoderado actualizados.")
        return redirect(reverse("alumnos:detalle", args=[v.alumno_id]) + "#apoderados")
    otros = v.apoderado.alumnos.exclude(pk=v.alumno_id)
    return render(request, "alumnos/vinculo_form.html", {"v": v, "form_apo": form_apo, "form_v": form_v, "otros": otros})


@permiso_requerido("alumnos.editar")
@require_POST
def vinculo_quitar(request, pk):
    v = get_object_or_404(AlumnoApoderado, pk=pk)
    alumno_pk, era_responsable, apoderado = v.alumno_id, v.responsable_pago, v.apoderado
    v.delete()
    if era_responsable:
        siguiente = AlumnoApoderado.objects.filter(alumno_id=alumno_pk).first()
        if siguiente:
            siguiente.responsable_pago = True
            siguiente.save()
    if not apoderado.vinculos.exists():
        apoderado.delete()  # ya no es apoderado de nadie
    messages.success(request, "Apoderado quitado.")
    return redirect(reverse("alumnos:detalle", args=[alumno_pk]) + "#apoderados")


# --- Importar ---------------------------------------------------------------

@permiso_requerido("alumnos.editar")
def plantilla(request):
    resp = HttpResponse(excel.plantilla(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="plantilla_alumnos.xlsx"'
    return resp


@permiso_requerido("alumnos.editar")
def importar(request):
    anio = AnioLectivo.actual()
    if anio is None:
        messages.warning(request, "Primero crea el año lectivo en Configuración.")
        return redirect("core:anio_nuevo")
    sesion_clave = "importacion_alumnos"

    # Paso 2: confirmar
    if request.method == "POST" and "confirmar" in request.POST:
        guardado = request.session.get(sesion_clave)
        if not guardado or guardado.get("anio") != anio.pk:
            messages.error(request, "La vista previa expiró. Vuelve a subir el archivo.")
            return redirect("alumnos:importar")
        resumen = excel.importar(guardado["filas"], anio)
        del request.session[sesion_clave]
        messages.success(
            request,
            f"Importación terminada: {resumen['nuevos']} alumnos nuevos, {resumen['actualizados']} actualizados, "
            f"{resumen['matriculas']} matrículas, {resumen['apoderados']} apoderados nuevos.",
        )
        return redirect("alumnos:lista")

    # Paso 1: subir y revisar
    form = ImportarForm(request.POST or None, request.FILES or None)
    contexto = {"form": form, "anio": anio}
    if request.method == "POST" and form.is_valid():
        filas, errores = excel.leer(form.cleaned_data["archivo"], anio)
        con_error = [f for f in filas if f["errores"]]
        contexto.update({"filas": filas, "errores": errores, "con_error": con_error})
        if filas and not con_error and not errores:
            request.session[sesion_clave] = {"anio": anio.pk, "filas": filas}
            contexto["listo"] = True
            contexto["nuevos"] = sum(1 for f in filas if f["accion"] == "Nuevo")
            contexto["actualizar"] = len(filas) - contexto["nuevos"]
        else:
            request.session.pop(sesion_clave, None)
    return render(request, "alumnos/importar.html", contexto)
