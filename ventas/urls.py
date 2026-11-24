from django.urls import path

from . import views

app_name = "ventas"

urlpatterns = [
    path("", views.pos, name="pos"),
    path("registrar/", views.registrar, name="registrar"),
    path("cotizar/", views.cotizar, name="cotizar"),
    path("lista/", views.lista, name="lista"),
    path("por-hacer/", views.por_hacer, name="por_hacer"),
    path("conciliar/", views.conciliar, name="conciliar"),
    path("conciliar/<str:fecha>/<str:metodo>/", views.conciliar_dia, name="conciliar_dia"),
    path("<int:pk>/", views.ticket, name="ticket"),
    path("<int:pk>/anular/", views.anular, name="anular"),
    path("<int:pk>/devolver/", views.devolver, name="devolver"),
    path("<int:pk>/imprimir/", views.imprimir, name="imprimir"),
]
