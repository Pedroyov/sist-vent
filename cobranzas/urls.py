from django.urls import path

from . import views

app_name = "cobranzas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("buscar/", views.buscar, name="buscar"),
    path("inscritos/", views.inscritos, name="inscritos"),
    path("inscribir/", views.nueva_inscripcion, name="inscribir"),
    path("inscripcion/<int:pk>/editar/", views.editar_inscripcion, name="editar_inscripcion"),
    path("inscripcion/<int:pk>/<str:accion>/", views.accion_inscripcion, name="accion_inscripcion"),
    path("cuota/<int:pk>/<str:accion>/", views.accion_cuota, name="accion_cuota"),
    path("cliente/<int:pk>/", views.cuenta, name="cuenta"),
    path("cliente/<int:pk>/cobrar/", views.cobrar_vista, name="cobrar"),
    path("recibo/<int:pk>/", views.recibo, name="recibo"),
    path("recibo/<int:pk>/anular/", views.anular, name="anular"),
    path("morosos/", views.morosos, name="morosos"),
    path("planes/", views.planes, name="planes"),
    path("planes/nuevo/", views.plan_form, name="plan_nuevo"),
    path("planes/<int:pk>/", views.plan_form, name="plan_editar"),
    path("configurar/", views.configurar, name="configurar"),
    path("reporte/", views.reporte, name="reporte"),
]
