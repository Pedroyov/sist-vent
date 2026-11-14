"""
Inicio (tablero): atajos, pendientes y resumen del día según los permisos de cada usuario.

Todo se calcula con lo que ya hay en el sistema; cada pendiente lleva a la pantalla
donde se resuelve y desaparece cuando ya no aplica.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db.models import Count, F, Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import AnioLectivo, Seccion
from .permisos import modulo_activo, puede
from .colegio import nombre as colegio_nombre
from .templatetags.sis import soles

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _pend(texto, url, icono="bi-exclamation-circle", color="warning", detalle=""):
    return {"texto": texto, "url": url, "icono": icono, "color": color, "detalle": detalle}


def _plural(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


class Tablero:
    def __init__(self, user):
        self.user = user
        self.hoy = timezone.localdate()
        self.anio = AnioLectivo.actual()
        self.atajos = []
        self.pendientes = []
        self.tarjetas = []
        self.faltaron = None
        self.caja = None
        self.alertas = []
        self.cumpleanos = []
        self.sin_clases = None
        self.mis_secciones, self.mis_cursos = [], []
        self.avance = None
        h = timezone.localtime().hour
        self.saludo = "Buenos días" if h < 12 else "Buenas tardes" if h < 19 else "Buenas noches"

    # ------------------------------------------------------------------
    def construir(self):
        if self.anio is None:
            return self
        from asistencia.servicios import motivo_no_lectivo

        self.sin_clases = motivo_no_lectivo(self.anio, self.hoy)
        self._atajos()
        if puede(self.user, "asistencia.tomar", "asistencia.todas"):
            self._asistencia_propia()
        if puede(self.user, "notas.registrar") and modulo_activo(self.user, "notas"):
            self._notas_propias()
        if puede(self.user, "asistencia.reportes"):
            self._asistencia_direccion()
        if puede(self.user, "notas.avance"):
            self._notas_direccion()
        if puede(self.user, "cobranza.ver"):
            self._cobranza()
        if puede(self.user, "programacion.editar"):
            self._programacion()
        if puede(self.user, "config.colegio"):
            self._anio_siguiente()
        self._tarjetas()
        self._cumpleanos()
        return self

    # ------------------------------------------------------------------
    def _atajos(self):
        a, u = self.atajos, self.user
        if puede(u, "cobranza.cobrar"):
            a.append({"texto": "Cobrar", "url": reverse("cobranza:inicio"), "icono": "bi-wallet2", "color": "success"})
            a.append({"texto": "Cobro rápido", "url": reverse("cobranza:rapido"), "icono": "bi-lightning-charge", "color": "success"})
        if puede(u, "cobranza.ver"):
            a.append({"texto": "Morosos", "url": reverse("cobranza:morosos"), "icono": "bi-exclamation-triangle", "color": "danger", "clave": "morosos"})
            a.append({"texto": "Caja de hoy", "url": reverse("cobranza:pagos"), "icono": "bi-cash-stack", "color": "info"})
        if puede(u, "asistencia.tomar", "asistencia.todas"):
            a.append({"texto": "Asistencia", "url": reverse("asistencia:hoy"), "icono": "bi-calendar-check", "color": "primary", "clave": "asistencia"})
        elif puede(u, "asistencia.reportes"):
            a.append({"texto": "Asistencia", "url": reverse("asistencia:resumen"), "icono": "bi-calendar-check", "color": "primary"})
        if puede(u, "notas.registrar", "notas.todas"):
            a.append({"texto": "Notas", "url": reverse("evaluacion:inicio"), "icono": "bi-journal-check", "color": "primary", "clave": "notas"})
        if modulo_activo(u, "programacion") and u.asignaciones.filter(seccion__anio_lectivo=self.anio).exists():
            a.append({"texto": "Mi horario", "url": reverse("academico:horario_docente", args=[u.pk]), "icono": "bi-clock", "color": "secondary"})
        if puede(u, "alumnos.editar"):
            a.append({"texto": "Nuevo alumno", "url": reverse("alumnos:nuevo"), "icono": "bi-person-plus", "color": "secondary"})
        elif puede(u, "alumnos.ver"):
            a.append({"texto": "Alumnos", "url": reverse("alumnos:lista"), "icono": "bi-people", "color": "secondary"})
        if puede(u, "notas.avance"):
            a.append({"texto": "Avance de notas", "url": reverse("evaluacion:avance"), "icono": "bi-bar-chart", "color": "secondary"})

    def _globo(self, clave, n):
        for a in self.atajos:
            if a.get("clave") == clave:
                a["globo"] = n

    # --- docente ---------------------------------------------------------
    def _asistencia_propia(self):
        from asistencia.servicios import mis_clases

        if self.sin_clases:
            return
        secs, asigs = mis_clases(self.user, self.anio, self.hoy)
        self.mis_secciones, self.mis_cursos = secs, asigs
        if puede(self.user, "asistencia.todas"):
            return  # quien supervisa ve el resumen de todos (abajo), no una lista enorme
        falta = [f"{s.grado.nombre} «{s.nombre}»" for s in secs if not s.sesion]
        falta += [f"{a.curso.corto} {a.seccion.grado.nombre} {a.seccion.nombre}" for a in asigs if a.toca_hoy and not a.sesion]
        if falta:
            self._globo("asistencia", len(falta))
            self.pendientes.append(_pend(
                f"Te falta tomar asistencia: {', '.join(falta[:4])}{'…' if len(falta) > 4 else ''}",
                reverse("asistencia:hoy"), "bi-calendar-x", "primary"))

    def _notas_propias(self):
        from academico.models import Asignacion
        from evaluacion.models import ConfigEvaluacion, Nota
        from evaluacion.servicios import periodo_actual

        periodo = periodo_actual(self.anio, self.hoy)
        if periodo is None or periodo.notas_cerradas or periodo.fecha_inicio > self.hoy:
            return
        asigs = list(Asignacion.objects.filter(seccion__anio_lectivo=self.anio, docente=self.user, curso__activo=True)
                     .select_related("curso", "seccion__grado__nivel"))
        if not asigs:
            return
        avance = avance_notas(self.anio, periodo, asigs)
        incompletas = [(a, avance[a.pk]) for a in asigs if avance[a.pk][0] < avance[a.pk][1]]
        dias = (periodo.fecha_fin - self.hoy).days
        if incompletas:
            self._globo("notas", len(incompletas))
            faltan = sum(e - h for _, (h, e) in incompletas)
            detalle = ", ".join(f"{a.curso.corto} {a.seccion.grado.nombre} {a.seccion.nombre}" for a, _ in incompletas[:4])
            self.pendientes.append(_pend(
                f"Faltan {faltan} notas del {periodo.nombre} en {_plural(len(incompletas), 'curso')}"
                + (f" · cierra en {_plural(dias, 'día')}" if 0 <= dias <= 21 else ""),
                reverse("evaluacion:inicio"), "bi-journal-x", "danger" if 0 <= dias <= 7 else "warning", detalle))
        # C (o desaprobado) sin conclusión descriptiva
        sin = 0
        for a in asigs:
            cfg = ConfigEvaluacion.de(self.anio, a.seccion.grado.nivel)
            q = Nota.objects.filter(asignacion=a, periodo=periodo, conclusion="")
            q = q.filter(numero__lt=cfg.nota_aprobatoria) if cfg.vigesimal else q.filter(letra="C")
            sin += q.count()
        if sin:
            self.pendientes.append(_pend(
                f"{_plural(sin, 'calificación', 'calificaciones')} desaprobatoria{'s' if sin != 1 else ''} sin conclusión descriptiva (el SIAGIE la pide)",
                reverse("evaluacion:inicio"), "bi-pencil-square", "warning"))

    # --- dirección ---------------------------------------------------------
    def _asistencia_direccion(self):
        from academico.models import Asignacion
        from asistencia.models import Sesion
        from core.models import ModoAsistencia

        if self.sin_clases:
            return
        diarias = Seccion.objects.filter(anio_lectivo=self.anio, modo_asistencia=ModoAsistencia.DIARIA)
        tomadas = set(Sesion.objects.filter(fecha=self.hoy, asignacion__isnull=True).values_list("seccion_id", flat=True))
        faltan = [s for s in diarias.select_related("tutor") if s.pk not in tomadas]
        dia = self.hoy.isoweekday()
        hora = timezone.localtime().time()
        # por curso: solo las clases que ya terminaron
        from academico.models import Clase

        clases = (Clase.objects.filter(seccion__anio_lectivo=self.anio, dia=dia, bloque__fin__lte=hora)
                  .values_list("asignacion_id", flat=True).distinct())
        hechas = set(Sesion.objects.filter(fecha=self.hoy, asignacion__isnull=False).values_list("asignacion_id", flat=True))
        cursos = list(Asignacion.objects.filter(pk__in=[c for c in clases if c not in hechas]).select_related("docente"))
        docentes = {s.tutor_id for s in faltan if s.tutor_id} | {a.docente_id for a in cursos if a.docente_id}
        if faltan or cursos:
            partes = []
            if faltan:
                partes.append(_plural(len(faltan), "sección", "secciones"))
            if cursos:
                partes.append(_plural(len(cursos), "clase") + " ya dictada" + ("s" if len(cursos) != 1 else ""))
            self.pendientes.append(_pend(
                f"Asistencia sin tomar hoy: {' y '.join(partes)} ({_plural(len(docentes), 'docente')})",
                reverse("asistencia:resumen"), "bi-calendar-x", "primary"))

    def _notas_direccion(self):
        from academico.models import Asignacion
        from evaluacion.servicios import periodo_actual

        periodo = periodo_actual(self.anio, self.hoy)
        if periodo is None or periodo.notas_cerradas or periodo.fecha_inicio > self.hoy:
            return
        dias = (periodo.fecha_fin - self.hoy).days
        asigs = list(Asignacion.objects.filter(seccion__anio_lectivo=self.anio, curso__activo=True)
                     .select_related("curso", "seccion__grado__nivel"))
        av = avance_notas(self.anio, periodo, asigs)
        hechas = sum(h for h, _ in av.values())
        esperadas = sum(e for _, e in av.values())
        if not esperadas:
            return
        pct = round(100 * hechas / esperadas)
        self.avance = {"periodo": periodo, "pct": pct, "dias": dias}
        if dias < 0:
            self.pendientes.append(_pend(f"El {periodo.nombre} ya terminó: revisa el avance ({pct}%) y ciérralo",
                                         reverse("evaluacion:configuracion"), "bi-lock", "danger"))
        elif dias <= 21 and pct < 100:
            sin_completar = len({a.docente_id for a in asigs if av[a.pk][0] < av[a.pk][1] and a.docente_id})
            self.pendientes.append(_pend(
                f"El {periodo.nombre} termina en {_plural(dias, 'día')}: notas al {pct}% ({_plural(sin_completar, 'docente')} sin completar)",
                reverse("evaluacion:avance"), "bi-hourglass-split", "danger" if dias <= 7 else "warning"))

    def _programacion(self):
        from academico.models import Asignacion
        from academico.programacion import control_carga

        sin_tutor = Seccion.objects.filter(anio_lectivo=self.anio, tutor__isnull=True).count()
        if sin_tutor:
            self.pendientes.append(_pend(f"{_plural(sin_tutor, 'sección', 'secciones')} sin tutor",
                                         reverse("academico:panel"), "bi-person-x", "warning"))
        sin_doc = Asignacion.objects.filter(seccion__anio_lectivo=self.anio, docente__isnull=True, curso__activo=True).count()
        if sin_doc:
            self.pendientes.append(_pend(f"{_plural(sin_doc, 'curso')} sin docente asignado",
                                         reverse("academico:docentes"), "bi-person-x", "warning"))
        for f in control_carga(self.anio):
            if f["problemas"]:
                self.pendientes.append(_pend(
                    f"{f['docente'].get_full_name() or f['docente'].username}: {f['problemas'][0].lower()}",
                    reverse("academico:carga"), "bi-speedometer", "danger"))

    def _anio_siguiente(self):
        if self.hoy.month < 11:
            return
        sig = self.anio.anio + 1
        if not AnioLectivo.objects.filter(anio=sig).exists():
            self.pendientes.append(_pend(
                f"Prepara el año {sig}: créalo y copia la programación para empezar las matrículas",
                reverse("core:anio_nuevo"), "bi-calendar-plus", "info"))

    # --- tesorería -------------------------------------------------------------
    def _cobranza(self):
        from cobranza.models import Cargo, ConfigCobranza, Pago

        if not ConfigCobranza.objects.filter(anio_lectivo=self.anio).exists():
            if puede(self.user, "cobranza.configurar"):
                self.pendientes.append(_pend(f"Configura los montos de matrícula y pensión de {self.anio}",
                                             reverse("cobranza:configuracion"), "bi-gear", "danger"))
            return
        cargos = Cargo.objects.filter(concepto__anio_lectivo=self.anio)
        vencidos = cargos.vencidos(self.hoy)
        saldo = F("monto") - F("descuento") - F("pagado")
        n_morosos = vencidos.values("alumno").distinct().count()
        if n_morosos:
            deuda = vencidos.aggregate(s=Sum(saldo))["s"] or Decimal(0)
            graves = (vencidos.filter(concepto__tipo="PEN").values("alumno").annotate(n=Count("id")).filter(n__gte=3).count())
            self._globo("morosos", n_morosos)
            self.pendientes.append(_pend(
                f"{_plural(n_morosos, 'alumno')} con deuda vencida ({soles(deuda)})"
                + (f" · {graves} deben 3 pensiones o más" if graves else ""),
                reverse("cobranza:morosos"), "bi-exclamation-triangle", "danger"))
            if graves:
                self.alertas.append({"texto": f"{_plural(graves, 'alumno')} con 3 pensiones vencidas o más",
                                     "url": reverse("cobranza:morosos") + "?min=3", "icono": "bi-cash-coin"})
        semana = cargos.pendientes().filter(vencimiento__gte=self.hoy, vencimiento__lte=self.hoy + timedelta(days=7))
        n_sem = semana.count()
        if n_sem:
            total = semana.aggregate(s=Sum(saldo))["s"] or Decimal(0)
            self.pendientes.append(_pend(
                f"Vencen esta semana: {n_sem} cuota{'s' if n_sem != 1 else ''} por {soles(total)}",
                reverse("cobranza:rapido"), "bi-calendar-event", "info",
                "Buen momento para mandar un recordatorio desde Morosos."))
        parciales = cargos.pendientes().filter(pagado__gt=0).count()
        if parciales:
            self.pendientes.append(_pend(f"{_plural(parciales, 'pago')} a cuenta por completar",
                                         reverse("cobranza:rapido"), "bi-hourglass", "secondary"))
        # caja del día
        pagos = Pago.objects.filter(fecha=self.hoy, anulado=False)
        por_metodo = [{"metodo": dict(Pago.Metodo.choices).get(m, m), "n": n, "total": t}
                      for m, n, t in pagos.values_list("metodo").annotate(n=Count("id"), t=Sum("total")).order_by("-t")]
        self.caja = {"total": sum((x["total"] for x in por_metodo), Decimal(0)), "n": sum(x["n"] for x in por_metodo),
                     "metodos": por_metodo}

    # --- tarjetas y resumen ------------------------------------------------------
    def _tarjetas(self):
        from alumnos.models import Matricula

        activos = Matricula.objects.filter(anio_lectivo=self.anio, estado=Matricula.Estado.MATRICULADO)
        if puede(self.user, "alumnos.ver"):
            self.tarjetas.append({"titulo": "Alumnos matriculados", "valor": activos.count(), "icono": "bi-people-fill",
                                  "color": "primary", "url": reverse("alumnos:lista")})
        else:
            from academico.models import Asignacion

            mias = Seccion.objects.filter(Q(tutor=self.user) | Q(asignaciones__docente=self.user), anio_lectivo=self.anio).distinct()
            if mias.exists():
                self.tarjetas.append({"titulo": "Mis alumnos", "valor": activos.filter(seccion__in=mias).count(),
                                      "icono": "bi-people-fill", "color": "primary", "url": ""})
                n = Asignacion.objects.filter(seccion__anio_lectivo=self.anio, docente=self.user, curso__activo=True).count()
                tutoria = mias.filter(tutor=self.user).first()
                self.tarjetas.append({"titulo": f"Tutor(a) de {tutoria.grado.nombre} «{tutoria.nombre}»" if tutoria else "Mis cursos",
                                      "valor": _plural(n, "curso"), "icono": "bi-easel", "color": "secondary", "url": ""})
        if modulo_activo(self.user, "asistencia") and puede(self.user, "asistencia.reportes", "asistencia.todas"):
            self._resumen_asistencia()
        if self.caja is not None:
            self.tarjetas.append({"titulo": "Cobrado hoy", "valor": soles(self.caja["total"]), "icono": "bi-cash-coin",
                                  "color": "info", "url": reverse("cobranza:pagos")})
            from cobranza.servicios import cobrado_en

            self.tarjetas.append({"titulo": "Cobrado este mes", "valor": soles(cobrado_en(self.hoy.replace(day=1), self.hoy)),
                                  "icono": "bi-graph-up", "color": "secondary", "url": reverse("cobranza:pagos") + f"?desde={self.hoy.replace(day=1):%Y-%m-%d}&hasta={self.hoy:%Y-%m-%d}"})

    def _resumen_asistencia(self):
        """Faltas del último día con clases y alumnos con 3 faltas seguidas."""
        from alumnos.models import Alumno, AlumnoApoderado
        from asistencia.models import Sesion
        from asistencia.servicios import estados_por_dia

        ultimo = Sesion.objects.filter(seccion__anio_lectivo=self.anio, fecha__lte=self.hoy).order_by("-fecha").values_list("fecha", flat=True).first()
        if ultimo is None:
            return
        desde = ultimo - timedelta(days=21)
        faltas_dia, total, presentes = [], 0, 0
        seguidas = []
        for sec in Seccion.objects.filter(anio_lectivo=self.anio, sesiones_asistencia__fecha__gte=desde).distinct().select_related("grado__nivel"):
            est = estados_por_dia(sec, desde, ultimo)
            por_alumno = defaultdict(dict)
            for (alumno_id, f), e in est.items():
                por_alumno[alumno_id][f] = e
            for alumno_id, dias in por_alumno.items():
                e = dias.get(ultimo)
                if e:
                    total += 1
                    presentes += e in ("P", "T")
                    if e == "F":
                        faltas_dia.append((alumno_id, sec))
                ult3 = [dias[f] for f in sorted(dias)[-3:]]
                if len(ult3) == 3 and all(x == "F" for x in ult3):
                    seguidas.append((alumno_id, sec))
        if total:
            self.tarjetas.insert(1, {
                "titulo": "Asistencia de hoy" if ultimo == self.hoy else f"Asistencia del {DIAS[ultimo.weekday()]}",
                "valor": f"{round(100 * presentes / total)} %", "icono": "bi-calendar-check-fill", "color": "success",
                "url": reverse("asistencia:resumen") + f"?fecha={ultimo:%Y-%m-%d}"})
        ids = {a for a, _ in faltas_dia} | {a for a, _ in seguidas}
        alumnos = {a.pk: a for a in Alumno.objects.filter(pk__in=ids)}
        apo = {}
        for v in AlumnoApoderado.objects.filter(alumno_id__in=ids).select_related("apoderado").order_by("-responsable_pago", "id"):
            apo.setdefault(v.alumno_id, v.apoderado)

        def fila(alumno_id, sec, texto):
            a, ap = alumnos[alumno_id], apo.get(alumno_id)
            msg = (f"Estimado(a) {ap.nombres.title() if ap else 'apoderado(a)'}, le escribimos de {colegio_nombre()}: "
                   f"{a.nombres.title()} {texto}. ¿Todo bien? Por favor, comuníquese con el tutor(a). Gracias.")
            return {"alumno": a, "seccion": sec, "apoderado": ap,
                    "wa": f"https://wa.me/{ap.whatsapp}?text={quote(msg)}" if ap and ap.whatsapp else None}

        cuando = "hoy" if ultimo == self.hoy else f"el {DIAS[ultimo.weekday()]} {ultimo:%d/%m}"
        self.faltaron = {"fecha": ultimo, "cuando": cuando,
                         "lista": sorted((fila(a, s, f"no asistió {cuando} a clases") for a, s in faltas_dia),
                                         key=lambda x: (x["seccion"].grado.nivel.orden, x["seccion"].grado.orden, x["alumno"].apellido_paterno))}
        for a, s in seguidas:
            f = fila(a, s, "faltó las últimas 3 clases")
            self.alertas.append({"texto": f"{f['alumno'].apellido_paterno} {f['alumno'].apellido_materno}, {f['alumno'].nombres}: 3 faltas seguidas",
                                 "detalle": f"{s.grado.nombre} «{s.nombre}» · {s.grado.nivel}", "url": reverse("alumnos:detalle", args=[a]),
                                 "wa": f["wa"], "icono": "bi-person-exclamation"})

    def _cumpleanos(self):
        from alumnos.models import Matricula

        if not puede(self.user, "alumnos.ver", "asistencia.tomar", "asistencia.todas", "notas.registrar"):
            return
        mats = Matricula.objects.filter(anio_lectivo=self.anio, estado=Matricula.Estado.MATRICULADO,
                                        alumno__fecha_nacimiento__month=self.hoy.month, alumno__fecha_nacimiento__day=self.hoy.day)
        if not puede(self.user, "alumnos.ver", "asistencia.todas"):
            mats = mats.filter(Q(seccion__tutor=self.user) | Q(seccion__asignaciones__docente=self.user)).distinct()
        for m in mats.select_related("alumno", "seccion__grado"):
            self.cumpleanos.append({"nombre": f"{m.alumno.nombres.split()[0].title()} {m.alumno.apellido_paterno.title()}",
                                    "detalle": f"{m.seccion.grado.nombre} «{m.seccion.nombre}» · cumple {m.alumno.edad}",
                                    "icono": "bi-mortarboard"})
        if modulo_activo(self.user, "personal"):
            from personal.models import Trabajador

            for t in Trabajador.objects.filter(activo=True, fecha_nacimiento__month=self.hoy.month, fecha_nacimiento__day=self.hoy.day):
                propio = t.usuario_id == self.user.pk
                self.cumpleanos.append({"nombre": f"{t.nombres.split()[0].title()} {t.apellidos.split()[0].title()}",
                                        "detalle": "¡Feliz cumpleaños! 🎉" if propio else t.get_cargo_display(),
                                        "icono": "bi-gift" if propio else "bi-person-badge"})


def avance_notas(anio, periodo, asignaciones):
    """{asignacion_id: (registradas, esperadas)} con pocas consultas."""
    from alumnos.models import Matricula
    from evaluacion.models import Competencia, ConfigEvaluacion, Nota

    hoy = timezone.localdate()
    fecha = min(periodo.fecha_fin, hoy) if periodo.fecha_inicio <= hoy else periodo.fecha_inicio
    secciones = {a.seccion_id for a in asignaciones}
    n_alumnos = dict(
        Matricula.objects.filter(seccion_id__in=secciones, fecha__lte=fecha)
        .filter(Q(estado=Matricula.Estado.MATRICULADO) | Q(fecha_retiro__gt=fecha))
        .values_list("seccion_id").annotate(n=Count("id")))
    n_comp = dict(Competencia.objects.filter(activo=True).values_list("curso_id").annotate(n=Count("id")))
    hechas = dict(Nota.objects.filter(periodo=periodo, asignacion__in=[a.pk for a in asignaciones])
                  .exclude(numero__isnull=True, letra="").values_list("asignacion_id").annotate(n=Count("id")))
    configs = {}
    res = {}
    for a in asignaciones:
        nivel = a.seccion.grado.nivel
        if nivel.pk not in configs:
            configs[nivel.pk] = ConfigEvaluacion.de(anio, nivel)
        comps = (n_comp.get(a.curso_id) or 1) if configs[nivel.pk].por_competencia else 1
        res[a.pk] = (hechas.get(a.pk, 0), n_alumnos.get(a.seccion_id, 0) * comps)
    return res
