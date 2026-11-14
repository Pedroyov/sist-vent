"""Competencias del Currículo Nacional (CNEB 2016) por área y nivel. Se pueden editar."""
from django.db import migrations

MAT = ["Resuelve problemas de cantidad", "Resuelve problemas de regularidad, equivalencia y cambio",
       "Resuelve problemas de forma, movimiento y localización", "Resuelve problemas de gestión de datos e incertidumbre"]
COM = ["Se comunica oralmente en su lengua materna", "Lee diversos tipos de textos escritos en su lengua materna",
       "Escribe diversos tipos de textos en su lengua materna"]
ING = ["Se comunica oralmente en inglés como lengua extranjera", "Lee diversos tipos de textos escritos en inglés como lengua extranjera",
       "Escribe diversos tipos de textos en inglés como lengua extranjera"]
AYC = ["Aprecia de manera crítica manifestaciones artístico-culturales", "Crea proyectos desde los lenguajes artísticos"]
CYT = ["Indaga mediante métodos científicos para construir sus conocimientos",
       "Explica el mundo físico basándose en conocimientos sobre los seres vivos, materia y energía, biodiversidad, Tierra y universo",
       "Diseña y construye soluciones tecnológicas para resolver problemas de su entorno"]
EF = ["Se desenvuelve de manera autónoma a través de su motricidad", "Asume una vida saludable",
      "Interactúa a través de sus habilidades sociomotrices"]
ER = ["Construye su identidad como persona humana, amada por Dios, digna, libre y trascendente",
      "Asume la experiencia del encuentro personal y comunitario con Dios en su proyecto de vida"]
PS = ["Construye su identidad", "Convive y participa democráticamente en la búsqueda del bien común",
      "Construye interpretaciones históricas", "Gestiona responsablemente el espacio y el ambiente",
      "Gestiona responsablemente los recursos económicos"]

COMPETENCIAS = {
    "Inicial": {"PS": PS[:2], "PSI": EF[:1], "COM": COM + AYC[1:], "MAT": [MAT[0], MAT[2]], "CYT": CYT[:1]},
    "Primaria": {"MAT": MAT, "COM": COM, "ING": ING, "PS": PS, "AYC": AYC, "CYT": CYT, "EF": EF, "ER": ER},
    "Secundaria": {"MAT": MAT, "COM": COM, "ING": ING, "AYC": AYC, "CCSS": PS[2:], "DPCC": PS[:2], "EF": EF,
                   "ER": ER, "CYT": CYT, "EPT": ["Gestiona proyectos de emprendimiento económico o social"]},
}


def crear(apps, schema_editor):
    Curso = apps.get_model("academico", "Curso")
    Competencia = apps.get_model("evaluacion", "Competencia")
    for curso in Curso.objects.select_related("nivel"):
        nombres = COMPETENCIAS.get(curso.nivel.nombre, {}).get(curso.abreviatura, [])
        for i, n in enumerate(nombres, start=1):
            Competencia.objects.get_or_create(curso=curso, nombre=n, defaults={"orden": i})


class Migration(migrations.Migration):
    dependencies = [("evaluacion", "0001_initial"), ("academico", "0002_cursos_iniciales")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
