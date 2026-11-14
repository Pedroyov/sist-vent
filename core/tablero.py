"""
Inicio (tablero): atajos, pendientes y números del día según los permisos de cada usuario.

Cada módulo nuevo agrega aquí su parte, por ejemplo:

    if puede(self.user, "ventas.vender"):
        self.atajos.append({"texto": "Vender", "url": reverse("ventas:pos"),
                            "icono": "bi-cart3", "color": "success"})
    if puede(self.user, "ventas.ver"):
        self.tarjetas.append({"titulo": "Ventas de hoy", "valor": soles(total),
                              "icono": "bi-graph-up", "color": "primary", "url": ...})
    self.pendientes.append(_pend("5 productos con stock bajo", reverse(...), "bi-box-seam", "danger"))
"""
from django.urls import reverse
from django.utils import timezone

from .permisos import puede


def _pend(texto, url, icono="bi-exclamation-circle", color="warning", detalle=""):
    return {"texto": texto, "url": url, "icono": icono, "color": color, "detalle": detalle}


def _plural(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


class Tablero:
    def __init__(self, user):
        self.user = user
        self.hoy = timezone.localdate()
        self.atajos = []
        self.pendientes = []
        self.tarjetas = []
        self.caja = None
        h = timezone.localtime().hour
        self.saludo = "Buenos días" if h < 12 else "Buenas tardes" if h < 19 else "Buenas noches"

    def construir(self):
        self._atajos()
        self._configuracion()
        if puede(self.user, "caja.usar", "caja.ver"):
            self._caja()
        if puede(self.user, "mesas.atender", "mesas.cobrar"):
            self._mesas()
        if puede(self.user, "ventas.vender", "ventas.ver"):
            self._ventas()
        if puede(self.user, "productos.ver"):
            self._productos()
        return self

    def _atajos(self):
        a, u = self.atajos, self.user
        if puede(u, "mesas.cocina"):
            a.append({"texto": "Pantalla de cocina", "url": reverse("mesas:cocina"), "icono": "bi-fire", "color": "warning"})
        if puede(u, "mesas.atender", "mesas.cobrar"):
            a.append({"texto": "Mesas", "url": reverse("mesas:mapa"), "icono": "bi-grid-3x3-gap", "color": "danger"})
        if puede(u, "ventas.vender"):
            a.append({"texto": "Vender", "url": reverse("ventas:pos"), "icono": "bi-cart-plus", "color": "success"})
        if puede(u, "ventas.vender", "ventas.ver"):
            a.append({"texto": "Ventas de hoy" if puede(u, "ventas.ver") else "Mis ventas", "url": reverse("ventas:lista"),
                      "icono": "bi-receipt", "color": "primary"})
        if puede(u, "productos.ver"):
            a.append({"texto": "Productos", "url": reverse("productos:lista"), "icono": "bi-box-seam", "color": "success"})
        if puede(u, "productos.stock"):
            a.append({"texto": "Movimientos de stock", "url": reverse("productos:kardex"), "icono": "bi-arrow-left-right", "color": "info"})
        if puede(u, "config.negocio"):
            a.append({"texto": "Datos del negocio", "url": reverse("core:datos_negocio"), "icono": "bi-shop", "color": "primary"})
        if puede(u, "config.usuarios"):
            a.append({"texto": "Usuarios", "url": reverse("core:usuario_lista"), "icono": "bi-person-gear", "color": "secondary"})

    def _configuracion(self):
        from .models import Ajustes

        if puede(self.user, "config.negocio") and not Ajustes.cargar().nombre:
            self.pendientes.append(_pend("Completa los datos del negocio", reverse("core:datos_negocio"), "bi-shop",
                                         detalle="Nombre, logo, RUC y contacto: salen en el ingreso y en los tickets."))

    def _caja(self):
        from caja.models import SesionCaja

        if puede(self.user, "caja.usar"):
            mia = SesionCaja.abierta_de(self.user)
            if mia is None:
                self.atajos.insert(0, {"texto": "Abrir caja", "url": reverse("caja:mi_caja"), "icono": "bi-unlock", "color": "warning"})
                if puede(self.user, "ventas.vender"):
                    self.pendientes.append(_pend("Abre tu caja para empezar a cobrar", reverse("caja:mi_caja"), "bi-safe2", "warning"))
            else:
                self.atajos.append({"texto": "Mi caja", "url": reverse("caja:sesion", args=[mia.pk]), "icono": "bi-safe2", "color": "dark"})
                if mia.de_dias_anteriores:
                    self.pendientes.append(_pend(f"Tu caja sigue abierta desde el {timezone.localtime(mia.abierta_en):%d/%m}",
                                                 reverse("caja:cerrar", args=[mia.pk]), "bi-safe2", "danger", "Ciérrala y abre una nueva."))
        if puede(self.user, "caja.ver"):
            viejas = [s for s in SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA).exclude(usuario=self.user).select_related("usuario")
                      if s.de_dias_anteriores]
            for s in viejas:
                self.pendientes.append(_pend(f"La caja de {s.usuario.get_full_name() or s.usuario.username} sigue abierta desde el {timezone.localtime(s.abierta_en):%d/%m}",
                                             reverse("caja:sesion", args=[s.pk]), "bi-safe2", "danger"))

    def _mesas(self):
        from mesas.models import Cuenta, Mesa

        abiertas = Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA)
        total = Mesa.objects.filter(activa=True).count()
        ocupadas = abiertas.filter(mesa__isnull=False).count()
        if total:
            self.tarjetas.append({"titulo": "Mesas ocupadas", "valor": f"{ocupadas} de {total}", "icono": "bi-grid-3x3-gap",
                                  "color": "danger" if ocupadas else "secondary", "url": reverse("mesas:mapa")})
        if puede(self.user, "mesas.cobrar"):
            n = abiertas.filter(pidio_cuenta=True).count()
            if n:
                self.pendientes.append(_pend(f"{_plural(n, 'mesa')} pidió la cuenta" if n == 1 else f"{n} mesas pidieron la cuenta",
                                             reverse("mesas:mapa"), "bi-receipt", "warning"))

    def _ventas(self):
        from ventas.models import Venta
        from ventas.servicios import resumen

        from .templatetags.sis import soles

        hoy = Venta.objects.filter(fecha__date=self.hoy)
        todas = puede(self.user, "ventas.ver")
        if not todas:
            hoy = hoy.filter(usuario=self.user)
        r = resumen(hoy)
        self.tarjetas.append({"titulo": "Vendido hoy" if todas else "Mis ventas de hoy", "valor": soles(r["total"]),
                              "icono": "bi-cash-stack", "color": "primary", "url": reverse("ventas:lista")})
        self.tarjetas.append({"titulo": f"Venta{'s' if r['n'] != 1 else ''} hoy", "valor": r["n"], "icono": "bi-receipt",
                              "color": "info", "url": reverse("ventas:lista")})
        self.caja = r if todas and r["n"] else None

    def _productos(self):
        from productos.models import Categoria, Producto
        from productos.views import por_reponer

        activos = Producto.objects.filter(activo=True).count()
        self.tarjetas.append({"titulo": "Productos activos", "valor": activos, "icono": "bi-box-seam",
                              "color": "success", "url": reverse("productos:lista")})
        reponer = por_reponer().values("producto_id").distinct().count()
        self.tarjetas.append({"titulo": "Por reponer", "valor": reponer, "icono": "bi-exclamation-triangle",
                              "color": "warning" if reponer else "secondary",
                              "url": reverse("productos:lista") + "?estado=reponer"})
        if reponer and puede(self.user, "productos.stock"):
            self.pendientes.append(_pend(f"{_plural(reponer, 'producto')} por reponer",
                                         reverse("productos:lista") + "?estado=reponer", "bi-box-seam", "danger",
                                         "Llegaron a su stock mínimo o se acabaron."))
        if not activos and puede(self.user, "productos.editar"):
            texto = "Registra tus productos o servicios"
            detalle = "Uno por uno o todos a la vez con la plantilla de Excel."
            if not Categoria.objects.exists():
                detalle = "Empieza creando las categorías (te sugerimos algunas según tu rubro)."
            self.pendientes.append(_pend(texto, reverse("productos:lista"), "bi-box-seam", "primary", detalle))
