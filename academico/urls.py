from django.urls import path

from . import views, views_programacion as prog

app_name = "academico"

urlpatterns = [
    # Panel de la programación del año
    path("", prog.panel, name="panel"),
    path("calendario/", prog.calendario, name="calendario"),
    path("calendario/<int:pk>/eliminar/", prog.calendario_eliminar, name="calendario_eliminar"),
    path("plan/", prog.plan, name="plan"),
    path("jornada/", prog.jornada, name="jornada"),
    path("horarios/", prog.horarios, name="horarios"),
    path("horarios/seccion/<int:seccion_pk>/", prog.horario_seccion, name="horario_seccion"),
    path("horarios/seccion/<int:seccion_pk>/celda/", prog.horario_celda, name="horario_celda"),
    path("horarios/seccion/<int:seccion_pk>/vaciar/", prog.horario_vaciar, name="horario_vaciar"),
    path("horarios/docente/<int:user_pk>/", prog.horario_docente, name="horario_docente"),
    path("copiar/", prog.copiar, name="copiar"),
    path("carga/", prog.carga, name="carga"),
    # Cursos y docentes
    path("docentes/", views.docentes, name="docentes"),
    path("cursos/", views.cursos, name="cursos"),
    path("cursos/nuevo/", views.curso_form, name="curso_nuevo"),
    path("cursos/<int:pk>/editar/", views.curso_form, name="curso_editar"),
    path("secciones/<int:seccion_pk>/", views.asignar, name="asignar"),
]
