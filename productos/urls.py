from django.urls import path

from . import views

app_name = "productos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("exportar/", views.exportar, name="exportar"),
    path("nuevo/", views.producto_form, name="nuevo"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.producto_form, name="editar"),
    path("<int:pk>/eliminar/", views.producto_eliminar, name="eliminar"),
    path("<int:pk>/stock/", views.movimiento, name="movimiento"),
    path("<int:pk>/variantes/generar/", views.variantes_generar, name="variantes_generar"),
    path("variantes/<int:pk>/editar/", views.variante_editar, name="variante_editar"),
    path("variantes/<int:pk>/eliminar/", views.variante_eliminar, name="variante_eliminar"),
    path("movimientos/", views.kardex, name="kardex"),
    path("categorias/", views.categorias, name="categorias"),
    path("categorias/sugeridas/", views.categorias_sugeridas, name="categorias_sugeridas"),
    path("categorias/<int:pk>/editar/", views.categoria_editar, name="categoria_editar"),
    path("categorias/<int:pk>/eliminar/", views.categoria_eliminar, name="categoria_eliminar"),
    path("importar/", views.importar, name="importar"),
    path("opciones/", views.opciones, name="opciones"),
    path("opciones/nuevo/", views.grupo_form, name="grupo_nuevo"),
    path("opciones/sugeridos/", views.grupos_sugeridos, name="grupos_sugeridos"),
    path("opciones/<int:pk>/", views.grupo_form, name="grupo_editar"),
    path("opciones/<int:pk>/eliminar/", views.grupo_eliminar, name="grupo_eliminar"),
    path("agotados/", views.agotados, name="agotados"),
    path("importar/plantilla/", views.plantilla, name="plantilla"),
]
