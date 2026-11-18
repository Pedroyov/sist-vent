from django.urls import path

from . import views

app_name = "personal"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.ficha, name="nuevo"),
    path("<int:pk>/", views.ficha, name="persona"),
]
