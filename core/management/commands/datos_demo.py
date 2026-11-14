"""
Llena el sistema con datos de ejemplo realistas para ver cómo se ve.

Uso (en una base de datos aparte, para no mezclar con los datos reales):
    demo.bat            (Windows: crea db_demo.sqlite3 y abre el sistema)
o bien:
    python manage.py datos_demo
"""
import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from academico import programacion
from academico.models import Asignacion, Bloque, Clase, Curso, HorasPlan
from alumnos.models import Alumno, AlumnoApoderado, Apoderado, Matricula
from asistencia.models import Asistencia, Sesion
from cobranza import servicios as cob
from cobranza.models import Cargo, ConfigCobranza, Concepto, Descuento, Pago
from core.models import AnioLectivo, DiaNoLectivo, ModoAsistencia, Nivel, Periodo, Seccion
from evaluacion.models import Comentario, Competencia, ConfigEvaluacion, Conducta, Nota
from personal.models import HorarioTrabajador, Trabajador

CLAVE = "demo1234"

AP = ("Quispe Flores Sánchez Rodríguez García Mamani Huamán Torres Ramírez Chávez Vargas Rojas Castillo "
      "Mendoza Gutiérrez Díaz Ramos Cruz Espinoza Salazar Paredes Córdova Rivera Herrera Medina Aguilar "
      "Vásquez Castro Morales Ortiz Romero Silva Palacios Cárdenas Ccori Condori Apaza Huanca Ticona "
      "Villanueva Benites Zapata Gonzales Pérez Lozano Campos Valdivia Navarro Alvarado").split()
NOM_M = ("Mateo Santiago Thiago Sebastián Leonardo Gael Adrián Diego Fabricio Joaquín Matías Alessandro "
         "Rodrigo Valentino Dylan Liam Bruno Gabriel Jhon Luis Carlos Piero Franco Josué André Nicolás").split()
NOM_F = ("Valentina Camila Luciana Mía Sofía Isabella Ariana Valeria Ximena Fernanda Antonella Abigail "
         "Danna Zoe Allison Kiara Nicole Brianna Alessia Daniela Milagros Lucía Rafaela Ana Flavia Renata").split()
NOM_AD_M = "Juan José Carlos Miguel Luis Jorge Víctor César Pedro Walter Raúl Edwin Óscar Julio".split()
NOM_AD_F = "María Rosa Carmen Elizabeth Ana Patricia Silvia Gladys Maritza Jessica Rocío Karina Lourdes".split()
OCUP = ["Comerciante", "Docente", "Enfermera", "Contador", "Ingeniero", "Independiente", "Ama de casa",
        "Taxista", "Administradora", "Técnico", "Policía", "Abogada", "Chef"]
CALLES = ["Av. Los Próceres", "Jr. Las Begonias", "Calle Los Pinos", "Av. Universitaria", "Jr. Huáscar",
          "Calle Las Gardenias", "Av. Túpac Amaru", "Jr. Ayacucho", "Calle Los Cedros", "Av. Primavera"]

# (usuario, nombres, apellidos, especialidad, nivel, cursos, modalidad, sueldo/pago hora, horas_max)
DOCENTES = [
    ("rcastillo", "Rosa", "Castillo Vega", "Educación Inicial", "Inicial", "*", "MES", 2100, 30),
    ("mpalacios", "Milagros", "Palacios Ruiz", "Educación Inicial", "Inicial", "*", "MES", 2100, 30),
    ("kzapata", "Karina", "Zapata León", "Educación Inicial", "Inicial", "*", "MES", 2100, 30),
    ("lmedina", "Lucía", "Medina Salas", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("jherrera", "Jorge", "Herrera Campos", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("pvargas", "Patricia", "Vargas Núñez", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("criveros", "César", "Riveros Lazo", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("gsalazar", "Gladys", "Salazar Ríos", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("evaldivia", "Edwin", "Valdivia Paz", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("smontes", "Silvia", "Montes Arce", "Educación Primaria", "Primaria", "*", "MES", 2400, 30),
    ("jsmith", "Jessica", "Smith Paredes", "Inglés", "Primaria", "ING", "HOR", 22, 30),
    ("wcardenas", "Walter", "Cárdenas Soto", "Educación Física", "Primaria", "EF", "HOR", 20, 30),
    ("vromero", "Víctor", "Romero Gil", "Religión", "Primaria", "ER", "HOR", 20, 30),
    ("lrios", "Luis", "Ríos Mendoza", "Matemática", "Secundaria", "MAT:1-3", "HOR", 25, 30),
    ("aflores", "Ana", "Flores Cueva", "Matemática / Física", "Secundaria", "MAT:4-5,CYT:4-5", "HOR", 25, 18),
    ("mgarcia", "María", "García Lino", "Comunicación", "Secundaria", "COM", "HOR", 25, 30),
    ("rbenites", "Raúl", "Benites Ochoa", "Inglés", "Secundaria", "ING", "HOR", 24, 30),
    ("ccondori", "Carmen", "Condori Apaza", "Ciencia y Tecnología", "Secundaria", "CYT:1-3", "HOR", 25, 30),
    ("jtorres", "Julio", "Torres Ramos", "Historia y Ciencias Sociales", "Secundaria", "CCSS,DPCC", "HOR", 24, 32),
    ("onavarro", "Óscar", "Navarro Díaz", "Arte", "Secundaria", "AYC,EPT", "HOR", 22, 30),
    ("eespinoza", "Elizabeth", "Espinoza Vila", "Educación Física", "Secundaria", "EF", "HOR", 20, 30),
    ("pcruz", "Pedro", "Cruz Alva", "Religión", "Secundaria", "ER", "HOR", 20, 30),
]

PLAN = {
    "Inicial": {"PS": 5, "PSI": 5, "COM": 5, "MAT": 5, "CYT": 5},
    "Primaria": {"MAT": 6, "COM": 6, "ING": 3, "PS": 3, "AYC": 3, "CYT": 4, "EF": 3, "ER": 2},
    "Secundaria": {"MAT": 5, "COM": 5, "ING": 3, "AYC": 2, "CCSS": 3, "DPCC": 3, "EF": 3, "ER": 2, "CYT": 5, "EPT": 4},
}
JORNADA = {  # inicio, minutos por hora, horas, recreos
    "Inicial": (time(8, 0), 40, 5, [(3, 30)]),
    "Primaria": (time(7, 45), 45, 6, [(3, 20), (5, 15)]),
    "Secundaria": (time(7, 45), 45, 7, [(3, 20), (5, 15)]),
}

CONCLUSIONES = [
    "Aún confunde los procedimientos básicos; necesita practicar con material concreto en casa.",
    "Tiene dificultad para comprender lo que lee; se recomienda lectura diaria acompañada.",
    "No entrega sus trabajos a tiempo y le cuesta organizar sus ideas por escrito.",
    "Le cuesta explicar sus respuestas; requiere acompañamiento y refuerzo en las tareas.",
    "Participa poco en clase y no logra aún los aprendizajes esperados del periodo.",
]
COMENTARIOS = [
    "Muy participativo, sigue así.", "Debe mejorar la puntualidad en la entrega de tareas.",
    "Buen avance en el bimestre.", "Se distrae con facilidad; conversar en casa.",
    "Demuestra interés y responsabilidad.", "Necesita repasar en casa los temas del bimestre.",
]


class Command(BaseCommand):
    help = "Carga datos de ejemplo (año 2026 con alumnos, pagos, asistencia, horarios y notas)."

    def add_arguments(self, parser):
        parser.add_argument("--forzar", action="store_true", help="Cargar aunque ya existan alumnos.")
        parser.add_argument("--semilla", type=int, default=2026)

    def handle(self, *args, **opts):
        if Alumno.objects.exists() and not opts["forzar"]:
            raise CommandError(
                "Esta base de datos ya tiene alumnos. Los datos de ejemplo van en una base aparte: usa demo.bat "
                "(o --forzar si de verdad quieres mezclarlos)."
            )
        self.r = random.Random(opts["semilla"])
        self.hoy = timezone.localdate()
        self.dnis = set()
        with transaction.atomic():
            self.anio_y_calendario()
            self.usuarios_y_personal()
            self.secciones()
            self.programacion()
            self.alumnos()
            self.cobranza()
            self.asistencia()
            self.notas()
        self.resumen()

    # --- utilidades --------------------------------------------------------

    def dni(self, base):
        while True:
            n = f"{base + self.r.randint(0, 999999):08d}"
            if n not in self.dnis:
                self.dnis.add(n)
                return n

    def celular(self):
        return "9" + "".join(str(self.r.randint(0, 9)) for _ in range(8))

    def log(self, texto):
        self.stdout.write(f"  · {texto}")

    # --- pasos --------------------------------------------------------------

    def anio_y_calendario(self):
        a = self.hoy.year if self.hoy.month >= 3 else self.hoy.year - 1
        self.anio, _ = AnioLectivo.objects.update_or_create(
            anio=a, defaults={"fecha_inicio": date(a, 3, 9), "fecha_fin": date(a, 12, 18), "activo": True,
                              "nombre": "Año de la Esperanza y el Fortalecimiento de la Democracia"},
        )
        fechas = [("I Bimestre", (3, 9), (5, 15)), ("II Bimestre", (5, 25), (7, 24)),
                  ("III Bimestre", (8, 10), (10, 9)), ("IV Bimestre", (10, 19), (12, 18))]
        self.periodos = []
        for i, (nom, ini, fin) in enumerate(fechas, start=1):
            p, _ = Periodo.objects.update_or_create(
                anio_lectivo=self.anio, numero=i,
                defaults={"nombre": nom, "fecha_inicio": date(a, *ini), "fecha_fin": date(a, *fin)},
            )
            p.notas_cerradas = p.fecha_fin < self.hoy
            p.save()
            self.periodos.append(p)
        programacion.cargar_feriados(self.anio)
        for desde, hasta, motivo in [((5, 18), (5, 22), "Vacaciones de medio bimestre"),
                                     ((7, 27), (8, 7), "Vacaciones de medio año"),
                                     ((10, 12), (10, 16), "Vacaciones de medio bimestre")]:
            DiaNoLectivo.objects.get_or_create(anio_lectivo=self.anio, fecha=date(a, *desde), defaults={
                "fecha_fin": date(a, *hasta), "motivo": motivo, "tipo": DiaNoLectivo.Tipo.VACACIONES})
        DiaNoLectivo.objects.get_or_create(anio_lectivo=self.anio, fecha=date(a, 7, 3), defaults={
            "motivo": "Día del Maestro (actividad)", "tipo": DiaNoLectivo.Tipo.OTRO})
        self.log(f"Año {a}, 4 bimestres, feriados y vacaciones")

    def usuario(self, username, nombres, apellidos, rol):
        u, creado = User.objects.get_or_create(username=username, defaults={
            "first_name": nombres, "last_name": apellidos, "email": f"{username}@colegio.demo"})
        if creado:
            u.set_password(CLAVE)
            u.save()
        u.groups.add(Group.objects.get(name=rol))
        return u

    def usuarios_y_personal(self):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "", CLAVE, first_name="Administrador")
        self.director = self.usuario("director", "Miguel", "Ángeles Rojas", "Dirección")
        self.tesorera = self.usuario("tesoreria", "Rocío", "Lozano Pérez", "Tesorería")
        base = date(self.anio.anio, 3, 1)
        otros = [
            (self.director, "Ángeles Rojas", "Miguel", "DIR", "Administración educativa", 4500),
            (self.tesorera, "Lozano Pérez", "Rocío", "TES", "Contabilidad", 1800),
            (None, "Benites Huanca", "Maritza", "ADM", "Secretariado", 1500),
            (None, "Paredes Ticona", "Lourdes", "AUX", "Auxiliar de educación", 1300),
            (None, "Condori Mamani", "Edgar", "LIM", "", 1130),
            (None, "Huamán Cruz", "Raúl", "SEG", "", 1200),
            (None, "Silva Ortiz", "Karla", "PSI", "Psicología", 1900),
        ]
        for u, ap, nom, cargo, esp, sueldo in otros:
            t = Trabajador.objects.create(
                usuario=u, numero_documento=self.dni(40000000), apellidos=ap, nombres=nom, cargo=cargo,
                especialidad=esp, celular=self.celular(), modalidad="MES", sueldo=sueldo,
                fecha_ingreso=base - timedelta(days=365 * self.r.randint(1, 9)),
            )
            ini, fin = (time(6, 30), time(14, 30)) if cargo in ("LIM", "SEG") else (time(7, 30), time(15, 30))
            if cargo == "PSI":
                ini, fin = time(8, 0), time(13, 0)
            HorarioTrabajador.objects.bulk_create(
                [HorarioTrabajador(trabajador=t, dia=d, inicio=ini, fin=fin) for d in range(1, 6)])
        self.docentes = {}
        for user, nom, ap, esp, nivel, cursos, modalidad, monto, hmax in DOCENTES:
            u = self.usuario(user, nom, ap, "Docente")
            Trabajador.objects.create(
                usuario=u, numero_documento=self.dni(10000000), apellidos=ap, nombres=nom, cargo="DOC",
                especialidad=esp, celular=self.celular(), email=u.email, modalidad=modalidad,
                sueldo=monto if modalidad == "MES" else 0, pago_hora=monto if modalidad == "HOR" else 0,
                horas_extra_semana=2 if modalidad == "HOR" else 0, horas_max_semana=hmax,
                fecha_ingreso=base - timedelta(days=365 * self.r.randint(0, 12)),
                fecha_nacimiento=date(self.r.randint(1965, 1998), self.r.randint(1, 12), self.r.randint(1, 28)),
                cuenta_bancaria=f"BCP 191-{self.r.randint(10000000, 99999999)}-0-{self.r.randint(10, 99)}",
            )
            self.docentes[user] = (u, nivel, cursos)
        self.log(f"{len(DOCENTES)} docentes y {len(otros)} trabajadores más (clave de todos: {CLAVE})")

    def secciones(self):
        self.secs = []
        tutores = {"Inicial": ["rcastillo", "mpalacios", "kzapata"],
                   "Primaria": ["lmedina", "jherrera", "pvargas", "criveros", "gsalazar", "evaldivia", "smontes"],
                   "Secundaria": ["lrios", "mgarcia", "ccondori", "jtorres", "aflores"]}
        for nivel in Nivel.objects.all():
            grados = list(nivel.grados.all())
            pendientes = list(tutores[nivel.nombre])
            for g in grados:
                nombres = ["A", "B"] if (nivel.nombre == "Primaria" and g.orden == 1) else (
                    ["Única"] if nivel.nombre == "Inicial" else ["A"])
                for n in nombres:
                    s = Seccion.objects.create(
                        anio_lectivo=self.anio, grado=g, nombre=n, vacantes=25 if nivel.nombre == "Inicial" else 30,
                        tutor=self.docentes[pendientes.pop(0)][0],
                        modo_asistencia=ModoAsistencia.POR_CURSO if nivel.nombre == "Secundaria" else ModoAsistencia.DIARIA,
                    )
                    self.secs.append(s)
        self.log(f"{len(self.secs)} secciones")

    def docente_para(self, seccion, curso):
        nivel = seccion.grado.nivel.nombre
        if nivel in ("Inicial", "Primaria") and curso.abreviatura not in ("ING", "EF", "ER"):
            return seccion.tutor
        for user, (u, niv, cursos) in self.docentes.items():
            if niv != nivel or cursos == "*":
                continue
            for parte in cursos.split(","):
                abrev, _, rango = parte.partition(":")
                if abrev != curso.abreviatura:
                    continue
                if not rango:
                    return u
                a, b = map(int, rango.split("-"))
                if a <= seccion.grado.orden <= b:
                    return u
        return None

    @staticmethod
    def minutos(b):
        return range(b.inicio.hour * 60 + b.inicio.minute, b.fin.hour * 60 + b.fin.minute, 5)

    def choca(self, ocupado, docente_id, dia, b):
        return docente_id is not None and any((docente_id, dia, m) in ocupado for m in self.minutos(b))

    def programacion(self):
        bloques = {}
        for nivel in Nivel.objects.all():
            ini, dur, n, recreos = JORNADA[nivel.nombre]
            programacion.generar_bloques(self.anio, nivel, ini, dur, n, recreos)
            bloques[nivel.pk] = list(Bloque.objects.filter(anio_lectivo=self.anio, nivel=nivel, tipo="CLA"))
            for curso in Curso.objects.filter(nivel=nivel, activo=True):
                horas = PLAN[nivel.nombre].get(curso.abreviatura, 0)
                for g in nivel.grados.all():
                    HorasPlan.objects.create(anio_lectivo=self.anio, grado=g, curso=curso, horas=horas)
        self.asig = {}
        for s in self.secs:
            for curso in Curso.objects.filter(nivel=s.grado.nivel, activo=True):
                if PLAN[s.grado.nivel.nombre].get(curso.abreviatura):
                    self.asig[(s.pk, curso.pk)] = Asignacion.objects.create(
                        seccion=s, curso=curso, docente=self.docente_para(s, curso))
        # horario sin cruces: reparto con reintentos
        for intento in range(200):
            ocupado, celdas, ok = set(), [], True
            for s in sorted(self.secs, key=lambda x: -x.grado.nivel.orden):
                libres = [(d, b) for d in range(1, 6) for b in bloques[s.grado.nivel_id]]
                pedidos = []
                for (sid, cid), a in self.asig.items():
                    if sid == s.pk:
                        pedidos += [a] * PLAN[s.grado.nivel.nombre][a.curso.abreviatura]
                self.r.shuffle(pedidos)
                pedidos.sort(key=lambda a: a.curso.abreviatura in ("ING", "EF", "ER") or a.docente_id == s.tutor_id)
                for a in pedidos:
                    opciones = [(d, b) for d, b in libres if not self.choca(ocupado, a.docente_id, d, b)]
                    # preferir no repetir el curso el mismo día más de 2 horas
                    opciones.sort(key=lambda x: (sum(1 for c in celdas if c[0] == s and c[1] == x[0] and c[3] == a), self.r.random()))
                    if not opciones:
                        ok = False
                        break
                    d, b = opciones[0]
                    libres.remove((d, b))
                    if a.docente_id:
                        for m in self.minutos(b):
                            ocupado.add((a.docente_id, d, m))
                    celdas.append((s, d, b, a))
                if not ok:
                    break
            if ok:
                break
        # orden por día para que se vea ordenado
        Clase.objects.bulk_create([Clase(seccion=s, dia=d, bloque=b, asignacion=a) for s, d, b, a in celdas])
        self.log(f"Plan de estudios, jornada y horario ({len(celdas)} horas de clase, intento {intento + 1})")

    def alumnos(self):
        r = self.r
        self.matriculas = []
        familias = []
        anio = self.anio.anio
        for s in self.secs:
            n = r.randint(14, 20) if s.grado.nivel.nombre != "Inicial" else r.randint(10, 15)
            edad = {"Inicial": 2, "Primaria": 5, "Secundaria": 11}[s.grado.nivel.nombre] + s.grado.orden
            for _ in range(n):
                sexo = r.choice("MF")
                # 1 de cada 8 es hermano de alguien ya registrado
                familia = r.choice(familias) if familias and r.random() < 0.12 else None
                if familia:
                    ap_p, ap_m, apos = familia
                else:
                    ap_p, ap_m = r.sample(AP, 2)
                    madre = Apoderado.objects.create(
                        numero_documento=self.dni(40000000), nombres=r.choice(NOM_AD_F),
                        apellidos=f"{ap_m} {r.choice(AP)}", celular=self.celular(),
                        email="" if r.random() < 0.5 else f"{ap_m.lower()}{r.randint(1, 99)}@gmail.com",
                        direccion=f"{r.choice(CALLES)} {r.randint(100, 1999)}", ocupacion=r.choice(OCUP))
                    apos = [(madre, "MADRE")]
                    if r.random() < 0.6:
                        padre = Apoderado.objects.create(
                            numero_documento=self.dni(40000000), nombres=r.choice(NOM_AD_M),
                            apellidos=f"{ap_p} {r.choice(AP)}", celular=self.celular(),
                            direccion=madre.direccion, ocupacion=r.choice(OCUP))
                        apos.append((padre, "PADRE"))
                    familias.append((ap_p, ap_m, apos))
                nac = date(anio - edad, r.randint(1, 12), r.randint(1, 28))
                a = Alumno.objects.create(
                    numero_documento=self.dni(70000000 + (anio - edad - 2005) * 400000),
                    codigo=f"{r.randint(10**13, 10**14 - 1)}",
                    apellido_paterno=ap_p, apellido_materno=ap_m,
                    nombres=" ".join(r.sample(NOM_M if sexo == "M" else NOM_F, r.choice([1, 2]))),
                    fecha_nacimiento=nac, sexo=sexo, direccion=apos[0][0].direccion,
                    observaciones=r.choice([""] * 12 + ["Alérgico a la penicilina.", "Asma leve: usa inhalador.",
                                                          "Usa lentes.", "Intolerancia a la lactosa."]),
                )
                for i, (apo, par) in enumerate(apos):
                    AlumnoApoderado.objects.create(alumno=a, apoderado=apo, parentesco=par, responsable_pago=i == 0)
                tipo = Matricula.Tipo.NUEVO if (s.grado.orden == 1 and s.grado.nivel.nombre == "Inicial") or r.random() < 0.1 \
                    else Matricula.Tipo.RATIFICACION
                m = Matricula(alumno=a, anio_lectivo=self.anio, seccion=s, tipo=tipo,
                              fecha=date(anio, 2, r.randint(1, 28)))
                self.matriculas.append(m)
                a.familia = familia is not None
        # la señal de cobranza necesita la configuración antes de matricular
        cfg = ConfigCobranza.objects.create(
            anio_lectivo=self.anio, monto_matricula=Decimal("300"), monto_pension=Decimal("380"),
            mes_inicio=3, mes_fin=12, dia_vencimiento=31, mora_activa=False)
        cob.generar_conceptos(cfg)
        self.config_cob = cfg
        for m in self.matriculas:
            m.save()
        # dos retiros y un traslado
        for m, est, f in [(self.matriculas[25], "RET", date(anio, 6, 20)), (self.matriculas[140], "TRA", date(anio, 8, 31)),
                          (self.matriculas[200], "RET", date(anio, 4, 30))]:
            m.estado, m.fecha_retiro = est, f
            m.observacion = "Se mudó a provincia" if est == "TRA" else "Retiro voluntario"
            m.save()
        # algunos cumpleaños hoy, para verlos en el inicio
        hoy = self.hoy
        for m in r.sample(self.matriculas, 3):
            if m.estado == "MAT":
                n = m.alumno.fecha_nacimiento
                try:
                    m.alumno.fecha_nacimiento = n.replace(month=hoy.month, day=hoy.day)
                except ValueError:
                    continue
                m.alumno.save(update_fields=["fecha_nacimiento"])
        Trabajador.objects.filter(usuario__username="lmedina").update(fecha_nacimiento=date(1988, hoy.month, min(hoy.day, 28)))
        self.log(f"{Alumno.objects.count()} alumnos, {Apoderado.objects.count()} apoderados")

    def cobranza(self):
        r, anio = self.r, self.anio
        # descuentos
        con_hermanos = [m for m in self.matriculas if getattr(m.alumno, "familia", False)]
        for m in con_hermanos:
            Descuento.objects.create(alumno=m.alumno, anio_lectivo=anio, motivo="Hermanos", tipo="POR", valor=10)
        for m in r.sample(self.matriculas, 4):
            Descuento.objects.get_or_create(alumno=m.alumno, anio_lectivo=anio, motivo="Media beca",
                                            defaults={"tipo": "POR", "valor": 50})
        hijo = self.matriculas[60]
        Descuento.objects.create(alumno=hijo.alumno, anio_lectivo=anio, motivo="Hijo de trabajador", tipo="MON", valor=100)
        # otros cobros
        agenda = Concepto.objects.create(anio_lectivo=anio, tipo="OTR", nombre="Agenda escolar", monto=25,
                                         vencimiento=date(anio.anio, 3, 31))
        paseo = Concepto.objects.create(anio_lectivo=anio, tipo="OTR", nombre="Paseo de fin de año", monto=60,
                                        vencimiento=date(anio.anio, 11, 20))
        promo = Concepto.objects.create(anio_lectivo=anio, tipo="OTR", nombre="Fiesta de promoción 5to", monto=150,
                                        vencimiento=date(anio.anio, 11, 10))
        for m in self.matriculas:
            Cargo.objects.create(alumno=m.alumno, concepto=agenda, monto=25, vencimiento=agenda.vencimiento)
            if m.seccion.grado.nivel.nombre == "Primaria":
                Cargo.objects.create(alumno=m.alumno, concepto=paseo, monto=60, vencimiento=paseo.vencimiento)
            if m.seccion.grado.nivel.nombre == "Secundaria" and m.seccion.grado.orden == 5:
                Cargo.objects.create(alumno=m.alumno, concepto=promo, monto=150, vencimiento=promo.vencimiento)
        # pagos según el perfil de cada familia
        metodos = ["EFE"] * 4 + ["YAP"] * 4 + ["PLI"] + ["TRA"] * 2 + ["DEP"]
        pagos = []
        for m in self.matriculas:
            perfil = r.choices(["puntual", "atrasa1", "atrasa2", "moroso"], weights=[62, 20, 10, 8])[0]
            atraso = {"puntual": 0, "atrasa1": 1, "atrasa2": 2, "moroso": r.randint(3, 5)}[perfil]
            cargos = list(Cargo.objects.filter(alumno=m.alumno, anulado=False).select_related("concepto"))
            limite = self.hoy - timedelta(days=30 * atraso)
            grupos = {}
            for c in cargos:
                if c.vencimiento > limite + timedelta(days=20) or c.saldo == 0:
                    continue
                # fecha en que pagó: cerca del vencimiento (algunos antes, otros unos días después)
                f = c.vencimiento - timedelta(days=r.randint(-12, 6) if perfil == "puntual" else r.randint(-25, 3))
                if c.concepto.tipo == "MAT":
                    f = m.fecha
                f = max(f, m.fecha)
                if f >= self.hoy:  # aún no le tocaba: algunos adelantan el pago, la mayoría no
                    if r.random() > 0.3:
                        continue
                    f = self.hoy - timedelta(days=r.randint(1, 13))
                if f.weekday() == 6:  # domingo no se atiende
                    f -= timedelta(days=1)
                grupos.setdefault(f, []).append(c)
            for f in sorted(grupos):
                items = [(c.pk, c.saldo, Decimal("0")) for c in grupos[f]]
                metodo = r.choice(metodos)
                pagos.append((f, m.alumno, items, metodo))
        pagos.sort(key=lambda x: x[0])
        for f, alumno, items, metodo in pagos:
            cob.registrar_pago(alumno=alumno, anio=anio, items=items, usuario=self.tesorera, fecha=f, metodo=metodo,
                                   numero_operacion=str(r.randint(10000000, 99999999)) if metodo != "EFE" else "")
        # un pago parcial y uno anulado
        deudor = next(m for m in self.matriculas if Cargo.objects.vencidos(self.hoy).filter(alumno=m.alumno, concepto__tipo="PEN").exists())
        c = Cargo.objects.vencidos(self.hoy).filter(alumno=deudor.alumno, concepto__tipo="PEN").first()
        cob.registrar_pago(alumno=deudor.alumno, anio=anio, items=[(c.pk, Decimal("200"), Decimal("0"))],
                           usuario=self.tesorera, fecha=self.hoy - timedelta(days=3), observacion="Pago a cuenta")
        ultimo = Pago.objects.filter(anulado=False).order_by("-numero")[5]
        cob.anular_pago(ultimo, self.director, "Se registró dos veces")
        Pago.objects.filter(pk=ultimo.pk).update(anulado_en=timezone.now())
        self.log(f"{Pago.objects.count()} pagos, {Descuento.objects.count()} descuentos, 3 otros cobros")

    def asistencia(self):
        r = self.r
        desde = self.hoy - timedelta(days=42)
        dias = programacion.dias_lectivos(self.anio, desde, self.hoy)
        faltones = set(m.alumno_id for m in r.sample(self.matriculas, 12))
        sesiones, regs = [], []
        activos = {}
        for m in self.matriculas:
            if m.estado == "MAT":
                activos.setdefault(m.seccion_id, []).append(m.alumno)
        clases = {}
        for c in Clase.objects.filter(seccion__anio_lectivo=self.anio).select_related("asignacion", "bloque"):
            clases.setdefault((c.seccion_id, c.dia), [])
            if c.asignacion not in clases[(c.seccion_id, c.dia)]:
                clases[(c.seccion_id, c.dia)].append(c.asignacion)

        def estado(alumno):
            p = r.random()
            f = 0.12 if alumno.pk in faltones else 0.03
            if p < f:
                return "F" if r.random() < 0.75 else "J"
            if p < f + 0.06:
                return "T"
            return "P"

        for dia in dias:
            for s in self.secs:
                alumnos = activos.get(s.pk, [])
                if s.por_curso:
                    if (self.hoy - dia).days > 14:
                        continue
                    for a in clases.get((s.pk, dia.isoweekday()), []):
                        if dia == self.hoy and r.random() < 0.5:
                            continue
                        ses = Sesion(seccion=s, fecha=dia, asignacion=a, tomado_por=a.docente or self.director)
                        sesiones.append((ses, alumnos))
                else:
                    if dia == self.hoy and r.random() < 0.4:
                        continue
                    sesiones.append((Sesion(seccion=s, fecha=dia, tomado_por=s.tutor or self.director), alumnos))
        Sesion.objects.bulk_create([x[0] for x in sesiones])
        for ses, alumnos in sesiones:
            # quien faltó en el día falta en todas sus clases
            for a in alumnos:
                regs.append(Asistencia(sesion=ses, alumno=a, estado=estado(a)))
        Asistencia.objects.bulk_create(regs, batch_size=2000)
        self.log(f"Asistencia de las últimas 6 semanas ({len(sesiones)} tomas)")

    def notas(self):
        r = self.r
        notas, comentarios, conductas = [], [], []
        habilidad = {m.alumno_id: r.gauss(0, 1) for m in self.matriculas}
        activos = {}
        for m in self.matriculas:
            activos.setdefault(m.seccion_id, []).append(m)
        comps = {}
        for c in Competencia.objects.filter(activo=True):
            comps.setdefault(c.curso_id, []).append(c)
        actual = next((p for p in self.periodos if p.fecha_inicio <= self.hoy <= p.fecha_fin), self.periodos[-1])

        def letra(h):
            x = h + r.gauss(0.2, 0.8)
            return "AD" if x > 1.3 else "A" if x > -0.1 else "B" if x > -1.2 else "C"

        def numero(h):
            return max(5, min(20, round(14 + h * 2.6 + r.gauss(0, 1.6))))

        for (sid, cid), asig in self.asig.items():
            s = asig.seccion
            cfg = ConfigEvaluacion.de(self.anio, s.grado.nivel)
            # en el bimestre actual, algunos docentes aún no terminan de registrar
            avance = r.choice([0, 0.4, 0.8, 1, 1])
            for p in self.periodos:
                if p.fecha_inicio > self.hoy:
                    continue
                if p == actual and avance == 0:
                    continue
                for m in activos.get(sid, []):
                    if m.fecha_retiro and m.fecha_retiro < p.fecha_inicio:
                        continue
                    if p == actual and r.random() > avance:
                        continue
                    h = habilidad[m.alumno_id]
                    for comp in comps.get(cid, []) if cfg.por_competencia else [None]:
                        if cfg.vigesimal:
                            v = numero(h)
                            concl = r.choice(CONCLUSIONES) if v < cfg.nota_aprobatoria and r.random() < 0.85 else ""
                            notas.append(Nota(alumno=m.alumno, asignacion=asig, periodo=p, competencia=comp,
                                              numero=v, conclusion=concl))
                        else:
                            v = letra(h)
                            concl = r.choice(CONCLUSIONES) if v == "C" and r.random() < 0.85 else ""
                            notas.append(Nota(alumno=m.alumno, asignacion=asig, periodo=p, competencia=comp,
                                              letra=v, conclusion=concl))
                    if cfg.comentarios and r.random() < 0.25:
                        comentarios.append(Comentario(alumno=m.alumno, asignacion=asig, periodo=p,
                                                      texto=r.choice(COMENTARIOS)))
        for s in self.secs:
            cfg = ConfigEvaluacion.de(self.anio, s.grado.nivel)
            if not cfg.conducta:
                continue
            for p in self.periodos:
                if p.fecha_fin > self.hoy:
                    continue
                for m in activos.get(s.pk, []):
                    if m.fecha_retiro and m.fecha_retiro < p.fecha_inicio:
                        continue
                    h = habilidad[m.alumno_id] * 0.6 + 0.5
                    if cfg.vigesimal:
                        conductas.append(Conducta(alumno=m.alumno, seccion=s, periodo=p, numero=numero(h)))
                    else:
                        conductas.append(Conducta(alumno=m.alumno, seccion=s, periodo=p, letra=letra(h)))
        Nota.objects.bulk_create(notas, batch_size=2000)
        Comentario.objects.bulk_create(comentarios, batch_size=2000)
        Conducta.objects.bulk_create(conductas, batch_size=2000)
        self.log(f"{len(notas)} notas, {len(comentarios)} comentarios, {len(conductas)} conductas")

    def resumen(self):
        self.stdout.write(self.style.SUCCESS("\nDatos de ejemplo cargados. Puedes entrar con:"))
        for u, rol in [("admin", "Administrador principal (módulos del sistema)"), ("director", "Dirección (ve todo)"), ("tesoreria", "Tesorería (cobranza)"),
                       ("lmedina", "Docente tutora de 1er grado A"), ("lrios", "Docente de Matemática, secundaria")]:
            self.stdout.write(f"   {u:<10} / {CLAVE}   → {rol}")
