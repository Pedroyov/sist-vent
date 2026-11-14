from django.urls import path

from . import views, views_config as cfg

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),

    # Configuración del colegio
    path("configuracion/", cfg.configuracion, name="configuracion"),
    path("configuracion/anios/", cfg.anio_lista, name="anio_lista"),
    path("configuracion/anios/nuevo/", cfg.anio_form, name="anio_nuevo"),
    path("configuracion/anios/<int:pk>/", cfg.anio_detalle, name="anio_detalle"),
    path("configuracion/anios/<int:pk>/editar/", cfg.anio_form, name="anio_editar"),
    path("configuracion/anios/<int:pk>/activar/", cfg.anio_activar, name="anio_activar"),

    path("configuracion/anios/<int:pk>/periodos/generar/", cfg.periodos_generar, name="periodos_generar"),
    path("configuracion/anios/<int:anio_pk>/periodos/nuevo/", cfg.periodo_form, name="periodo_nuevo"),
    path("configuracion/periodos/<int:pk>/editar/", cfg.periodo_form, name="periodo_editar"),
    path("configuracion/periodos/<int:pk>/eliminar/", cfg.periodo_eliminar, name="periodo_eliminar"),

    path("configuracion/anios/<int:anio_pk>/secciones/crear/", cfg.secciones_crear, name="secciones_crear"),
    path("configuracion/anios/<int:anio_pk>/secciones/nueva/", cfg.seccion_form, name="seccion_nueva"),
    path("configuracion/secciones/<int:pk>/editar/", cfg.seccion_form, name="seccion_editar"),
    path("configuracion/secciones/<int:pk>/eliminar/", cfg.seccion_eliminar, name="seccion_eliminar"),

    path("configuracion/usuarios/", cfg.usuario_lista, name="usuario_lista"),
    path("configuracion/usuarios/nuevo/", cfg.usuario_form, name="usuario_nuevo"),
    path("configuracion/usuarios/<int:pk>/editar/", cfg.usuario_form, name="usuario_editar"),
    path("configuracion/colegio/", cfg.datos_colegio, name="datos_colegio"),
    path("configuracion/roles/", cfg.roles, name="roles"),
    path("configuracion/modulos/", cfg.modulos, name="modulos"),
    path("configuracion/roles/nuevo/", cfg.rol_form, name="rol_nuevo"),
    path("configuracion/roles/<int:pk>/editar/", cfg.rol_form, name="rol_editar"),
    path("configuracion/roles/<int:pk>/eliminar/", cfg.rol_eliminar, name="rol_eliminar"),

    # PWA: se sirven desde la raíz para que el service worker controle todo el sitio
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("archivos/<path:ruta>", views.archivo, name="archivo"),
]
