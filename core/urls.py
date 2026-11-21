from django.urls import path

from . import views, views_config as cfg, views_seguridad as seg

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),

    # Configuración
    path("configuracion/usuarios/", cfg.usuario_lista, name="usuario_lista"),
    path("configuracion/usuarios/nuevo/", cfg.usuario_form, name="usuario_nuevo"),
    path("configuracion/usuarios/<int:pk>/editar/", cfg.usuario_form, name="usuario_editar"),
    path("configuracion/negocio/", cfg.datos_negocio, name="datos_negocio"),
    path("configuracion/roles/", cfg.roles, name="roles"),
    path("configuracion/modulos/", cfg.modulos, name="modulos"),
    path("configuracion/bitacora/", cfg.bitacora, name="bitacora"),
    path("configuracion/usuarios/<int:pk>/quitar-codigo/", seg.quitar_codigo, name="quitar_codigo"),
    path("configuracion/roles/nuevo/", cfg.rol_form, name="rol_nuevo"),
    path("configuracion/roles/<int:pk>/editar/", cfg.rol_form, name="rol_editar"),
    path("configuracion/roles/<int:pk>/eliminar/", cfg.rol_eliminar, name="rol_eliminar"),

    # PWA: se sirven desde la raíz para que el service worker controle todo el sitio
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("archivos/<path:ruta>", views.archivo, name="archivo"),
]
