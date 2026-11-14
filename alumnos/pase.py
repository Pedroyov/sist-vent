"""
Pase de año: matricula en bloque a los alumnos de un año en el grado siguiente
del año destino, con revisión previa.
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import AnioLectivo, Grado, Seccion
from core.permisos import permiso_requerido

from .models import Matricula


def _siguiente_grado():
    """{grado_id: grado_siguiente_id o None si egresa}"""
    grados = list(Grado.objects.order_by("nivel__orden", "orden").values_list("id", flat=True))
    return {g: (grados[i + 1] if i + 1 < len(grados) else None) for i, g in enumerate(grados)}


def _anios(request):
    anios = list(AnioLectivo.objects.order_by("anio"))
    destino = origen = None
    d, o = request.GET.get("destino") or request.POST.get("destino"), request.GET.get("origen") or request.POST.get("origen")
    if d and d.isdigit():
        destino = next((a for a in anios if a.pk == int(d)), None)
    if destino is None and anios:
        destino = anios[-1]  # por defecto, el año más reciente (el que empieza)
    if o and o.isdigit():
        origen = next((a for a in anios if a.pk == int(o)), None)
    if origen is None and destino is not None:
        anteriores = [a for a in anios if a.anio < destino.anio]
        origen = anteriores[-1] if anteriores else None
    return anios, origen, destino


def _propuesta(origen, destino):
    sig = _siguiente_grado()
    secciones_destino = list(
        Seccion.objects.filter(anio_lectivo=destino)
        .select_related("grado__nivel")
        .annotate(ocupadas=Count("matriculas", filter=Q(matriculas__estado=Matricula.Estado.MATRICULADO)))
        .order_by("grado__nivel__orden", "grado__orden", "nombre")
    )
    por_grado = {}
    for s in secciones_destino:
        por_grado.setdefault(s.grado_id, []).append(s)

    ya_en_destino = set(Matricula.objects.filter(anio_lectivo=destino).values_list("alumno_id", flat=True))
    mats = (
        Matricula.objects.filter(anio_lectivo=origen, estado=Matricula.Estado.MATRICULADO)
        .select_related("alumno", "seccion__grado__nivel")
        .order_by("seccion__grado__nivel__orden", "seccion__grado__orden", "seccion__nombre",
                  "alumno__apellido_paterno", "alumno__apellido_materno", "alumno__nombres")
    )
    filas, egresan, ya, sin_seccion = [], [], [], set()
    for m in mats:
        if m.alumno_id in ya_en_destino:
            ya.append(m)
            continue
        siguiente = sig.get(m.seccion.grado_id)
        if siguiente is None:
            egresan.append(m)
            continue
        opciones = por_grado.get(siguiente, [])
        propuesta = next((s for s in opciones if s.nombre == m.seccion.nombre), opciones[0] if opciones else None)
        if propuesta is None:
            sin_seccion.add(Grado.objects.select_related("nivel").get(pk=siguiente))
        filas.append({"m": m, "propuesta": propuesta})
    return filas, egresan, ya, sorted(sin_seccion, key=lambda g: (g.nivel.orden, g.orden)), secciones_destino


@permiso_requerido("alumnos.pase")
def pase_de_anio(request):
    anios, origen, destino = _anios(request)
    contexto = {"anios": anios, "origen": origen, "destino": destino}
    if origen is None or destino is None or origen.pk == destino.pk:
        contexto["sin_anios"] = True
        return render(request, "alumnos/pase.html", contexto)

    accion = request.POST.get("accion")

    if request.method == "POST" and accion == "copiar_secciones":
        creadas = 0
        with transaction.atomic():
            for s in Seccion.objects.filter(anio_lectivo=origen):
                _, nueva = Seccion.objects.get_or_create(
                    anio_lectivo=destino, grado=s.grado, nombre=s.nombre,
                    defaults={"turno": s.turno, "vacantes": s.vacantes, "tutor": s.tutor, "modo_asistencia": s.modo_asistencia},
                )
                creadas += nueva
        messages.success(request, f"Se copiaron {creadas} secciones de {origen} a {destino}.")
        return redirect(f"{reverse('alumnos:pase')}?origen={origen.pk}&destino={destino.pk}")

    filas, egresan, ya, sin_seccion, secciones_destino = _propuesta(origen, destino)

    if request.method == "POST" and accion == "confirmar":
        validas = {s.pk: s for s in secciones_destino}
        elegidos = []
        for f in filas:
            m = f["m"]
            if request.POST.get(f"inc_{m.alumno_id}") != "on":
                continue
            sec_id = request.POST.get(f"sec_{m.alumno_id}", "")
            seccion = validas.get(int(sec_id)) if sec_id.isdigit() else None
            if seccion is None:
                messages.error(request, f"Elige la sección de {m.alumno.nombre_completo}.")
                break
            f["propuesta"] = seccion
            elegidos.append((m.alumno, seccion))
        else:
            # control de vacantes
            nuevos = {}
            for _, s in elegidos:
                nuevos[s.pk] = nuevos.get(s.pk, 0) + 1
            llenas = [
                f"{validas[pk].grado.nombre} «{validas[pk].nombre}» ({validas[pk].ocupadas + n}/{validas[pk].vacantes})"
                for pk, n in nuevos.items() if validas[pk].ocupadas + n > validas[pk].vacantes
            ]
            if llenas:
                messages.error(request, "Estas secciones superan sus vacantes: " + ", ".join(llenas) + ". Aumenta las vacantes en Configuración o reparte a los alumnos.")
            elif not elegidos:
                messages.warning(request, "No marcaste ningún alumno.")
            else:
                hoy = timezone.localdate()
                with transaction.atomic():
                    Matricula.objects.bulk_create([
                        Matricula(alumno=a, anio_lectivo=destino, seccion=s, tipo=Matricula.Tipo.RATIFICACION, fecha=hoy)
                        for a, s in elegidos
                    ])
                    # bulk_create no dispara señales: generar aquí las deudas de cobranza
                    from cobranza.servicios import sincronizar_anio

                    sincronizar_anio(destino)
                messages.success(request, f"Se matricularon {len(elegidos)} alumnos en {destino}.")
                return redirect(f"{reverse('alumnos:lista')}?anio={destino.pk}")
        # si hubo error, se mantiene lo que el usuario marcó
        for f in filas:
            f["excluido"] = request.POST.get(f"inc_{f['m'].alumno_id}") != "on"

    contexto.update({
        "filas": filas, "egresan": egresan, "ya": ya, "sin_seccion": sin_seccion,
        "secciones_destino": secciones_destino,
        "origen_tiene_secciones": Seccion.objects.filter(anio_lectivo=origen).exists(),
    })
    return render(request, "alumnos/pase.html", contexto)
