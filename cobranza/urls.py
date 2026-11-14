from django.urls import path

from . import views, views_otros, views_rapido, views_reportes

app_name = "cobranza"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("rapido/", views_rapido.rapido, name="rapido"),
    path("rapido/<int:cargo_pk>/", views_rapido.rapido_form, name="rapido_form"),
    path("rapido/<int:cargo_pk>/pagar/", views_rapido.rapido_pagar, name="rapido_pagar"),
    path("rapido/lote/<int:concepto_pk>/", views_rapido.rapido_lote, name="rapido_lote"),
    path("pagos/", views.pagos, name="pagos"),
    path("alumno/<int:alumno_pk>/", views.cobrar, name="cobrar"),
    path("alumno/<int:alumno_pk>/descuentos/agregar/", views.descuento_agregar, name="descuento_agregar"),
    path("descuentos/<int:pk>/eliminar/", views.descuento_eliminar, name="descuento_eliminar"),
    path("recibo/<int:pk>/", views.recibo, name="recibo"),
    path("recibo/<int:pk>/anular/", views.anular, name="anular"),
    path("pagos/excel/", views_reportes.pagos_excel, name="pagos_excel"),
    path("morosos/", views_reportes.morosos, name="morosos"),
    path("morosos/<int:alumno_pk>/aviso/", views_reportes.registrar_aviso, name="registrar_aviso"),
    path("otros/", views_otros.lista, name="otros"),
    path("otros/nuevo/", views_otros.nuevo, name="otro_nuevo"),
    path("otros/<int:pk>/", views_otros.detalle, name="otro_detalle"),
    path("otros/<int:pk>/eliminar/", views_otros.eliminar, name="otro_eliminar"),
    path("otros/cargo/<int:cargo_pk>/quitar/", views_otros.quitar, name="otro_quitar"),
]
