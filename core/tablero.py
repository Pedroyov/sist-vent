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
        h = timezone.localtime().hour
        self.saludo = "Buenos días" if h < 12 else "Buenas tardes" if h < 19 else "Buenas noches"

    def construir(self):
        self._atajos()
        self._configuracion()
        return self

    def _atajos(self):
        a, u = self.atajos, self.user
        if puede(u, "config.negocio"):
            a.append({"texto": "Datos del negocio", "url": reverse("core:datos_negocio"), "icono": "bi-shop", "color": "primary"})
        if puede(u, "config.usuarios"):
            a.append({"texto": "Usuarios", "url": reverse("core:usuario_lista"), "icono": "bi-person-gear", "color": "secondary"})

    def _configuracion(self):
        from .models import Ajustes

        if puede(self.user, "config.negocio") and not Ajustes.cargar().nombre:
            self.pendientes.append(_pend("Completa los datos del negocio", reverse("core:datos_negocio"), "bi-shop",
                                         detalle="Nombre, logo, RUC y contacto: salen en el ingreso y en los tickets."))
