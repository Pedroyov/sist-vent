from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from core.models import AnioLectivo, Nivel, Seccion
from core.permisos import permiso_requerido

from .models import Asignacion, Curso

User = get_user_model()


def _docentes():
    return User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class CursoForm(forms.ModelForm):
    class Meta:
        model = Curso
        fields = ["nivel", "nombre", "abreviatura", "orden", "activo"]


# --- Cursos -----------------------------------------------------------------

@permiso_requerido("programacion.editar")
def cursos(request):
    niveles = Nivel.objects.prefetch_related(
        Prefetch("cursos", queryset=Curso.objects.annotate(n=Count("asignaciones")))
    )
    return render(request, "academico/cursos.html", {"niveles": niveles})


@permiso_requerido("programacion.editar")
def curso_form(request, pk=None):
    curso = get_object_or_404(Curso, pk=pk) if pk else None
    inicial = {}
    if not curso and request.GET.get("nivel", "").isdigit():
        nivel_id = int(request.GET["nivel"])
        inicial = {"nivel": nivel_id, "orden": Curso.objects.filter(nivel_id=nivel_id).count() + 1}
    form = CursoForm(request.POST or None, instance=curso, initial=inicial)
    if request.method == "POST" and form.is_valid():
        c = form.save()
        messages.success(request, f"Curso «{c}» guardado.")
        return redirect("academico:cursos")
    return render(request, "core/form.html", {
        "form": form, "titulo": "Editar curso" if curso else "Nuevo curso",
        "cancelar": reverse("academico:cursos"), "breadcrumb": [("Cursos", reverse("academico:cursos"))],
    })


# --- Cursos y docentes de una sección ---------------------------------------

@permiso_requerido("programacion.editar")
def asignar(request, seccion_pk):
    seccion = get_object_or_404(Seccion.objects.select_related("grado__nivel", "anio_lectivo", "tutor"), pk=seccion_pk)
    cursos = list(Curso.objects.filter(nivel=seccion.grado.nivel, activo=True))
    actuales = {a.curso_id: a for a in seccion.asignaciones.annotate(n_sesiones=Count("sesiones"))}
    docentes = list(_docentes())

    if request.method == "POST":
        validos = {str(d.pk): d for d in docentes}
        avisos, cambios = [], 0
        with transaction.atomic():
            # tutor y modo de asistencia
            tutor = validos.get(request.POST.get("tutor", ""))
            modo = request.POST.get("modo_asistencia")
            if tutor != seccion.tutor or (modo in ("DIA", "CUR") and modo != seccion.modo_asistencia):
                seccion.tutor = tutor
                if modo in ("DIA", "CUR"):
                    seccion.modo_asistencia = modo
                seccion.save(update_fields=["tutor", "modo_asistencia"])
                cambios += 1
            for c in cursos:
                dicta = request.POST.get(f"dicta_{c.pk}") == "on"
                docente = validos.get(request.POST.get(f"docente_{c.pk}", ""))
                a = actuales.get(c.pk)
                if dicta and a is None:
                    Asignacion.objects.create(seccion=seccion, curso=c, docente=docente)
                    cambios += 1
                elif dicta and a.docente_id != (docente.pk if docente else None):
                    a.docente = docente
                    a.save(update_fields=["docente"])
                    cambios += 1
                elif not dicta and a is not None:
                    if a.n_sesiones:
                        avisos.append(f"«{c}» ya tiene asistencias registradas: se mantiene.")
                    else:
                        a.delete()
                        cambios += 1
        messages.success(request, f"Sección {seccion.grado.nombre} «{seccion.nombre}» actualizada.")
        for a in avisos:
            messages.warning(request, a)
        # ¿algún docente de esta sección supera su máximo de horas?
        from .programacion import control_carga

        ids = set(seccion.asignaciones.exclude(docente__isnull=True).values_list("docente_id", flat=True))
        for f in control_carga(seccion.anio_lectivo):
            if f["docente"].pk in ids and f["maximo"] is not None and f["plan"] > f["maximo"]:
                messages.warning(request, f"{f['docente'].get_full_name() or f['docente'].username} queda con {f['plan']} h y su máximo es {f['maximo']} h.")
        siguiente = request.POST.get("siguiente", "")
        if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            siguiente = reverse("academico:asignar", args=[seccion.pk])
        return redirect(siguiente)

    from .programacion import horas_plan, resumen_carga

    hp = horas_plan(seccion.anio_lectivo)
    carga = resumen_carga(seccion.anio_lectivo)
    for d in docentes:
        d.horas = carga[d.pk]["plan"] if d.pk in carga else 0
    filas = [{"curso": c, "asignacion": actuales.get(c.pk), "horas": hp.get((seccion.grado_id, c.pk))} for c in cursos]
    hermanas = Seccion.objects.filter(anio_lectivo=seccion.anio_lectivo).select_related("grado__nivel").order_by(
        "grado__nivel__orden", "grado__orden", "nombre"
    )
    lista = list(hermanas)
    i = next((k for k, s in enumerate(lista) if s.pk == seccion.pk), 0)
    return render(request, "academico/asignar.html", {
        "seccion": seccion, "anio": seccion.anio_lectivo, "filas": filas, "docentes": docentes, "nuevo": not actuales,
        "anterior": lista[i - 1] if i > 0 else None, "siguiente": lista[i + 1] if i + 1 < len(lista) else None,
    })


@permiso_requerido("programacion.editar")
def docentes(request):
    """Carga de cada docente en el año: tutorías y cursos."""
    anio = AnioLectivo.actual()
    asignaciones = (
        Asignacion.objects.filter(seccion__anio_lectivo=anio)
        .select_related("curso", "seccion__grado__nivel", "docente")
        .order_by("seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre", "curso__orden")
    )
    por_docente, sin_docente = {}, []
    for a in asignaciones:
        if a.docente_id:
            por_docente.setdefault(a.docente, {"cursos": [], "tutorias": []})["cursos"].append(a)
        else:
            sin_docente.append(a)
    for s in Seccion.objects.filter(anio_lectivo=anio, tutor__isnull=False).select_related("tutor", "grado__nivel"):
        por_docente.setdefault(s.tutor, {"cursos": [], "tutorias": []})["tutorias"].append(s)
    filas = sorted(por_docente.items(), key=lambda kv: (kv[0].get_full_name() or kv[0].username).lower())
    secciones = Seccion.objects.filter(anio_lectivo=anio).select_related("grado__nivel", "tutor").annotate(
        n_cursos=Count("asignaciones")
    ).order_by("grado__nivel__orden", "grado__orden", "nombre") if anio else []
    from .programacion import resumen_carga

    carga = resumen_carga(anio) if anio else {}
    for d, c in filas:
        c["horas"] = carga[d.pk]["plan"] if d.pk in carga else 0
    return render(request, "academico/docentes.html", {
        "anio": anio, "filas": filas, "sin_docente": sin_docente, "secciones": secciones,
    })
