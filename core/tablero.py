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
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .permisos import puede
from .turnos import por_confirmar
from .utils import dias


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
        if puede(self.user, "reservas.ver"):
            self._reservas()
        if puede(self.user, "citas.ver", "citas.gestionar", "citas.mi_agenda"):
            self._citas()
        if puede(self.user, "ventas.vender", "ventas.ver"):
            self._ventas()
        if puede(self.user, "cobranzas.ver"):
            self._cobranzas()
        if puede(self.user, "clientes.ver"):
            self._clientes()
        if puede(self.user, "productos.ver"):
            self._productos()
        if puede(self.user, "facturacion.ver"):
            self._facturacion()
        if puede(self.user, "compras.ver"):
            self._compras()
        if puede(self.user, "ventas.conciliar"):
            self._conciliacion()
        return self

    def _conciliacion(self):
        """Yape, Plin, tarjeta o transferencias con movimiento y sin conciliar hace más de 2 días."""
        from ventas.conciliacion import pendientes

        for p in pendientes(self.hoy):
            self.pendientes.append(_pend(f"{p['nombre']} sin conciliar desde el {p['desde']:%d/%m}", reverse("ventas:conciliar"),
                                         "bi-bank", "warning", f"{_plural(p['dias'], 'día')} con cobros sin comparar con el banco."))

    def _compras(self):
        """Pagos a proveedores vencidos o que vencen en los próximos 7 días."""
        from compras.servicios import vencen_pronto

        lista = vencen_pronto(7)
        if not lista:
            return
        vencidas = [c for c in lista if c.vence < self.hoy]
        total = sum(c.saldo for c in (vencidas or lista))
        texto = (f"{_plural(len(vencidas), 'pago')} a proveedores vencido{'s' if len(vencidas) != 1 else ''}" if vencidas
                 else f"{_plural(len(lista), 'pago')} a proveedores vence{'n' if len(lista) != 1 else ''} esta semana")
        self.pendientes.append(_pend(texto, reverse("compras:por_pagar"), "bi-truck", "danger" if vencidas else "warning",
                                     f"S/ {total:.2f} en total."))

    def _facturacion(self):
        """Comprobantes que SUNAT aún no recibe: pasado el plazo pierden validez."""
        from datetime import timedelta

        from facturacion.servicios import atrasados, vence_envio

        lista = list(atrasados()[:50])
        if not lista:
            return
        vence = min(vence_envio(c) for c in lista)
        urgente = vence <= self.hoy + timedelta(days=1)
        self.pendientes.insert(0, _pend(
            f"{_plural(len(lista), 'comprobante')} sin aceptar por SUNAT", reverse("facturacion:lista") + "?estado=falta",
            "bi-receipt-cutoff", "danger" if urgente else "warning",
            f"El más antiguo vence el {vence:%d/%m}. Reenvíalos; si siguen fallando, revisa el internet o el proveedor."))

    def _atajos(self):
        from .glosario import palabras
        from .models import Ajustes

        a, u, t = self.atajos, self.user, palabras(Ajustes.cargar())
        if puede(u, "mesas.cocina"):
            a.append({"texto": "Pantalla de cocina", "url": reverse("mesas:cocina"), "icono": "bi-fire", "color": "warning"})
        if puede(u, "mesas.atender", "mesas.cobrar"):
            a.append({"texto": "Mesas", "url": reverse("mesas:mapa"), "icono": "bi-grid-3x3-gap", "color": "danger"})
        if puede(u, "citas.ver", "citas.gestionar"):
            a.append({"texto": "Citas", "url": reverse("citas:agenda"), "icono": "bi-calendar2-week", "color": "primary"})
        if puede(u, "citas.gestionar"):
            a.append({"texto": "Nueva cita", "url": reverse("citas:nueva"), "icono": "bi-calendar-plus", "color": "info"})
        if puede(u, "citas.mi_agenda") and not puede(u, "citas.gestionar"):
            a.append({"texto": "Registrar servicio", "url": reverse("citas:registrar"), "icono": "bi-scissors", "color": "success"})
        if puede(u, "citas.mi_agenda"):
            a.append({"texto": "Mi agenda", "url": reverse("citas:mi_agenda"), "icono": "bi-person-badge", "color": "success"})
        if puede(u, "reservas.ver"):
            a.append({"texto": "Reservas", "url": reverse("reservas:agenda"), "icono": "bi-calendar-event", "color": "primary"})
        if puede(u, "delivery.atender", "delivery.cobrar"):
            a.append({"texto": "Delivery", "url": reverse("mesas:pedidos"), "icono": "bi-scooter", "color": "danger"})
        if puede(u, "cobranzas.ver"):
            a.append({"texto": t["cobranzas"], "url": reverse("cobranzas:inicio"), "icono": "bi-calendar-check", "color": "primary"})
        if puede(u, "cobranzas.inscribir"):
            a.append({"texto": t["inscribir"], "url": reverse("cobranzas:inscribir"), "icono": "bi-person-plus", "color": "info"})
        if puede(u, "ventas.vender"):
            a.append({"texto": t["vender"], "url": reverse("ventas:pos"), "icono": "bi-cart-plus", "color": "success"})
        if puede(u, "ventas.vender", "ventas.ver"):
            a.append({"texto": "Ventas de hoy" if puede(u, "ventas.ver") else "Mis ventas", "url": reverse("ventas:lista"),
                      "icono": "bi-receipt", "color": "primary"})
        if puede(u, "clientes.ver"):
            a.append({"texto": "Clientes", "url": reverse("clientes:lista"), "icono": "bi-people", "color": "secondary"})
        if puede(u, "productos.ver"):
            a.append({"texto": t["productos"], "url": reverse("productos:lista"), "icono": "bi-box-seam", "color": "success"})
        if puede(u, "productos.stock"):
            a.append({"texto": "Movimientos de stock", "url": reverse("productos:kardex"), "icono": "bi-arrow-left-right", "color": "info"})
        if puede(u, "reportes.ver"):
            a.append({"texto": "Reportes", "url": reverse("reportes:inicio"), "icono": "bi-bar-chart", "color": "info"})
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

    def _reservas(self):
        from reservas.servicios import atrasadas, cerrar_pasadas, resumen_dia
        from reservas.models import Reserva

        cerrar_pasadas(self.hoy)
        r = resumen_dia(self.hoy)
        url = reverse("reservas:agenda")
        self.tarjetas.append({"titulo": f"Reservas de hoy · {_plural(r['personas'], 'persona')}" if r["n"] else "Reservas de hoy", "valor": r["n"],
                              "icono": "bi-calendar-event", "color": "primary" if r["n"] else "secondary", "url": url})
        tarde = atrasadas()
        if tarde:
            nombres = ", ".join(f"{x.nombre} ({x.hora:%H:%M})" for x in tarde[:3])
            self.pendientes.append(_pend(f"{_plural(len(tarde), 'reserva')} sin llegar: {nombres}", url, "bi-hourglass-bottom", "danger",
                                         "Márcalas como «Llegaron» o «No vino»."))
        if puede(self.user, "reservas.gestionar"):
            n = por_confirmar(Reserva, self.hoy)
            if n:
                self.pendientes.append(_pend(f"{_plural(n, 'reserva')} por confirmar (hoy y mañana)", url, "bi-whatsapp", "warning",
                                             "Confírmalas por WhatsApp."))

    def _citas(self):
        from citas.models import Cita
        from personal.models import Persona
        from citas.servicios import cerrar_pasadas, resumen_dia

        cerrar_pasadas(self.hoy)
        todas = puede(self.user, "citas.ver", "citas.gestionar")
        mio = None if todas else Persona.objects.filter(usuario=self.user, atiende_citas=True).first()
        if not todas and mio is None:
            return
        r = resumen_dia(self.hoy, mio)
        url = reverse("citas:agenda") if todas else reverse("citas:mi_agenda")
        self.tarjetas.append({"titulo": "Citas de hoy" if todas else "Mis citas de hoy", "valor": r["n"], "icono": "bi-calendar2-week",
                              "color": "primary" if r["n"] else "secondary", "url": url})
        if todas and not Persona.objects.filter(atiende_citas=True).exists() and puede(self.user, "personal.editar"):
            self.pendientes.append(_pend("Registra a tu personal y sus horarios para empezar a dar citas", reverse("personal:lista"),
                                         "bi-people", "primary"))
        if puede(self.user, "ventas.vender", "citas.gestionar"):
            from citas.servicios import contar_por_cobrar

            n = contar_por_cobrar()
            if n:
                self.pendientes.append(_pend(f"{_plural(n, 'servicio')} hecho{'s' if n != 1 else ''} por cobrar", reverse("citas:por_cobrar"),
                                             "bi-scissors", "info", "El personal ya avisó: cóbralos en caja."))
        if puede(self.user, "citas.gestionar"):
            n = por_confirmar(Cita, self.hoy)
            if n:
                self.pendientes.append(_pend(f"{_plural(n, 'cita')} por confirmar (hoy y mañana)", url, "bi-whatsapp", "warning",
                                             "Confírmalas por WhatsApp."))

    def _ventas(self):
        from ventas.models import Venta
        from ventas.servicios import resumen

        from .templatetags.sis import soles

        hoy = Venta.objects.filter(**dias("fecha", self.hoy))
        todas = puede(self.user, "ventas.ver")
        if not todas:
            hoy = hoy.filter(usuario=self.user)
        r = resumen(hoy)
        self.tarjetas.append({"titulo": "Vendido hoy" if todas else "Mis ventas de hoy", "valor": soles(r["total"]),
                              "icono": "bi-cash-stack", "color": "primary", "url": reverse("ventas:lista")})
        self.tarjetas.append({"titulo": f"Venta{'s' if r['n'] != 1 else ''} hoy", "valor": r["n"], "icono": "bi-receipt",
                              "color": "info", "url": reverse("ventas:lista")})
        self.caja = r if todas and r["n"] else None

    def _cobranzas(self):
        from cobranzas.models import Plan
        from cobranzas.servicios import al_dia, resumen

        from .templatetags.sis import soles

        if not Plan.objects.exists():
            if puede(self.user, "cobranzas.gestionar"):
                self.pendientes.append(_pend("Crea tus planes de cobranza", reverse("cobranzas:planes"), "bi-calendar-check", "primary",
                                             "El precio y cada cuánto se paga (mensual, por curso, pago único)."))
            return
        al_dia()
        r = resumen()
        self.tarjetas.append({"titulo": "Cobrado este mes (cuotas)", "valor": soles(r["cobrado_mes"]), "icono": "bi-cash-coin",
                              "color": "success", "url": reverse("cobranzas:inicio")})
        self.tarjetas.append({"titulo": "Cuotas vencidas", "valor": soles(r["vencido"]), "icono": "bi-exclamation-circle",
                              "color": "danger" if r["vencido"] else "secondary", "url": reverse("cobranzas:morosos")})
        if r["morosos"]:
            self.pendientes.append(_pend(f"{_plural(r['morosos'], 'persona')} con cuotas vencidas ({soles(r['vencido'])})",
                                         reverse("cobranzas:morosos"), "bi-calendar-x", "danger", "Mándales el recordatorio por WhatsApp."))
        if r["por_vencer"]:
            self.pendientes.append(_pend(f"Cuotas por vencer: {soles(r['por_vencer'])}", reverse("cobranzas:morosos") + "?ver=proximos",
                                         "bi-hourglass-split", "warning"))

    def _clientes(self):
        from clientes.servicios import total_por_cobrar

        from .templatetags.sis import soles

        total = total_por_cobrar()
        if total > 0:
            self.tarjetas.append({"titulo": "Por cobrar (fiado)", "valor": soles(total), "icono": "bi-journal-text",
                                  "color": "warning", "url": reverse("clientes:lista") + "?ver=deben"})
            from clientes.servicios import vencidos

            atrasos = vencidos()
            if atrasos:
                monto = sum(a["monto"] for a in atrasos.values())
                self.pendientes.append(_pend(f"{_plural(len(atrasos), 'cliente')} con fiado vencido", reverse("clientes:lista") + "?ver=vencido",
                                             "bi-journal-x", "danger", f"{soles(monto)} vencido. Recuérdales desde su ficha."))

    def _productos(self):
        from productos.models import Categoria, Producto
        from productos.servicios import por_reponer

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
