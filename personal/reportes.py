"""Reporte de Personal: uno solo para todos los negocios.

Junta lo que hace cada persona según los módulos que use el negocio:
- **Cobró en caja** (siempre): todo lo que cobró con su usuario: ventas, y también cuotas (Cobranzas) y pagos de
  deudas (Clientes), con el detalle de cada uno y el ticket promedio de sus ventas.
- **Atendió** (Mesas o la función «Quién atendió»): ventas que atendió como mozo o vendedor, y las propinas.
- **Servicios** (Citas): servicios hechos, clientes, sin cita, no vino, ocupación y lo que más hizo; y el **tiempo real por
  servicio** (solo lo que se marcó con Empezar y Terminar, con un solo servicio en esa atención) frente al del catálogo.
- **Entregas** (Delivery): pedidos que repartió.
- **Comisión** (función «Comisiones»): su % sobre lo que generó (servicios + lo que atendió).

Cada fila es una Persona del Personal; un usuario que no está en el Personal sale con su nombre de usuario (así el
reporte funciona aunque el negocio nunca registre a su personal).
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from core.utils import dias

from .models import Persona

CERO = Decimal("0")


def _fila(clave, nombre, persona=None):
    return {"clave": clave, "nombre": nombre, "persona": persona, "color": persona.color if persona else "#adb5bd",
            "cobro_n": 0, "cobro": CERO, "ventas_n": 0, "ventas": CERO, "cuotas_n": 0, "cuotas": CERO, "deudas_n": 0, "deudas": CERO,
            "atendio_n": 0, "atendio": CERO, "propinas": CERO,
            "servicios": 0, "servicios_total": CERO, "clientes": set(), "sin_cita": 0, "no_vino": 0, "minutos": 0,
            "por_servicio": Counter(), "entregas": 0}


def reporte(desde, hasta, modulos, comisiones=False, atendio=False):
    from ventas.models import Venta

    personas = {p.pk: p for p in Persona.objects.select_related("usuario")}
    por_usuario = {p.usuario_id: p for p in personas.values() if p.usuario_id}
    por_nombre = {p.nombre.strip().lower(): p for p in personas.values()}
    filas = {}

    def de_persona(p):
        return filas.setdefault(f"p{p.pk}", _fila(f"p{p.pk}", p.nombre, p))

    def de_usuario(u):
        if u is None:
            return None
        if u.pk in por_usuario:
            return de_persona(por_usuario[u.pk])
        return filas.setdefault(f"u{u.pk}", _fila(f"u{u.pk}", u.get_full_name() or u.username))

    ventas = list(Venta.objects.filter(**dias("fecha", desde, hasta), estado=Venta.Estado.PAGADA)
                  .select_related("usuario", "atendio", "atendio_persona"))
    citas_por_venta = {}
    if "citas" in modulos:
        from citas.models import Cita

        for vid, precio in Cita.objects.filter(venta__in=[v.pk for v in ventas]).values_list("venta_id", "precio"):
            citas_por_venta[vid] = citas_por_venta.get(vid, CERO) + (precio or CERO)
    con_atendio = "mesas" in modulos or atendio
    for v in ventas:
        f = de_usuario(v.usuario)
        if f is not None:
            f["ventas_n"] += 1
            f["ventas"] += v.total
        if con_atendio:
            g = de_persona(v.atendio_persona) if v.atendio_persona_id else de_usuario(v.atendio)
            if g is not None:
                g["atendio_n"] += 1
                g["atendio"] += max(v.total - citas_por_venta.get(v.pk, CERO), CERO)  # los servicios ya cuentan en «Servicios»
                g["propinas"] += v.propina or CERO

    # Devoluciones del periodo: restan a quien cobró la venta y a quien la atendió
    from ventas.devoluciones import en_periodo

    for d in en_periodo(desde, hasta).select_related("venta__usuario", "venta__atendio", "venta__atendio_persona"):
        v = d.venta
        f = de_usuario(v.usuario)
        if f is not None:
            f["ventas"] -= d.total
        if con_atendio:
            g = de_persona(v.atendio_persona) if v.atendio_persona_id else de_usuario(v.atendio)
            if g is not None:
                g["atendio"] = max(g["atendio"] - d.total, CERO)

    # Otros cobros que también entran a la caja de quien cobra
    cobros = []
    if "cobranzas" in modulos:
        from cobranzas.models import Pago

        cobros.append(("cuotas", Pago))
    if "clientes" in modulos:
        from clientes.models import Abono

        cobros.append(("deudas", Abono))
    for campo, modelo in cobros:
        for p in (modelo.objects.filter(anulado=False, **dias("fecha", desde, hasta)).exclude(metodo__in=["INC", "DEV"])
                  .select_related("usuario")):  # incobrables y devoluciones no son dinero cobrado
            f = de_usuario(p.usuario)
            f[f"{campo}_n"] += 1
            f[campo] += p.monto

    tabla, columnas, tiempos, ocupacion = [], [], [], (hasta - desde).days <= 92
    if "citas" in modulos:
        from citas.models import Cita
        from citas.servicios import Dia

        servicios = {}
        citas = list(Cita.objects.filter(fecha__gte=desde, fecha__lte=hasta).select_related("profesional", "servicio__producto"))
        tiempos = _tiempos_reales(citas)
        for c in citas:
            f = de_persona(c.profesional)
            if c.estado == Cita.Estado.ATENDIDA:
                f["servicios"] += 1
                f["servicios_total"] += c.precio or CERO
                f["clientes"].add(c.cliente_id or c.telefono or c.nombre.lower())
                f["sin_cita"] += c.sin_cita
                f["minutos"] += c.minutos
                nombre = c.servicio.producto.nombre if c.servicio_id else (c.servicio_nombre or "Otro")
                f["por_servicio"][nombre] += 1
                servicios.setdefault(nombre, Counter())[c.profesional_id] += 1
            elif c.estado == Cita.Estado.NO_VINO:
                f["no_vino"] += 1
        jornada = {}
        if ocupacion:
            dia = desde
            while dia <= min(hasta, timezone.localdate()):
                d = Dia(dia)
                for p in personas.values():
                    if p.atiende_citas:
                        jornada[p.pk] = jornada.get(p.pk, 0) + sum(b - a for a, b in d.jornada(p))
                dia += timedelta(days=1)
        for f in filas.values():
            p = f["persona"]
            f["ocupacion"] = round(f["minutos"] * 100 / jornada[p.pk]) if p and ocupacion and jornada.get(p.pk) else None
        columnas = sorted({personas[pid] for cnt in servicios.values() for pid in cnt}, key=lambda p: (p.orden, p.nombre))
        tabla = [{"servicio": n, "total": sum(cnt.values()), "por": [cnt.get(p.pk, 0) for p in columnas]}
                 for n, cnt in sorted(servicios.items(), key=lambda x: -sum(x[1].values()))]

    if "delivery" in modulos:
        from mesas.models import Cuenta

        for nombre in (Cuenta.objects.filter(tipo=Cuenta.Tipo.DELIVERY, estado=Cuenta.Estado.COBRADA, **dias("abierta_en", desde, hasta))
                       .exclude(repartidor="").values_list("repartidor", flat=True)):
            p = por_nombre.get(nombre.strip().lower())
            f = de_persona(p) if p else filas.setdefault(f"r{nombre.lower()}", _fila(f"r{nombre.lower()}", nombre))
            f["entregas"] += 1

    lista = []
    for f in filas.values():
        f["cobro_n"] = f["ventas_n"] + f["cuotas_n"] + f["deudas_n"]
        f["cobro"] = f["ventas"] + f["cuotas"] + f["deudas"]
        f["promedio"] = (f["ventas"] / f["ventas_n"]).quantize(Decimal("0.01")) if f["ventas_n"] else None
        f["clientes"] = len(f["clientes"])
        f["top"] = f["por_servicio"].most_common(3)
        f["generado"] = f["servicios_total"] + f["atendio"]
        f.setdefault("ocupacion", None)
        p = f["persona"]
        f["pct_comision"] = p.comision if p else CERO
        f["comision"] = (f["generado"] * f["pct_comision"] / 100).quantize(Decimal("0.01")) if comisiones else None
        if any((f["cobro_n"], f["atendio_n"], f["servicios"], f["no_vino"], f["entregas"])):
            lista.append(f)
    lista.sort(key=lambda f: (-f["generado"], -f["servicios"], -f["cobro"], f["nombre"]))
    maximo = max((f["generado"] or f["cobro"] for f in lista), default=0) or 1
    for f in lista:
        f["pct"] = round(float(f["generado"] or f["cobro"]) / float(maximo) * 100, 1)
    ver = {"cuotas": "cobranzas" in modulos, "deudas": "clientes" in modulos, "atendio": con_atendio, "propinas": "mesas" in modulos, "servicios": "citas" in modulos,
           "ocupacion": "citas" in modulos and ocupacion, "entregas": "delivery" in modulos, "comisiones": comisiones}
    return {"filas": lista, "ver": ver, "tabla": tabla, "columnas": columnas, "tiempos": tiempos,
            "servicios": sum(f["servicios"] for f in lista), "generado": sum((f["generado"] for f in lista), CERO),
            "comision_total": sum((f["comision"] or CERO for f in lista), CERO)}


def _tiempos_reales(citas):
    """Cuánto dura de verdad cada servicio: promedio de lo marcado con Empezar y Terminar, contando solo las atenciones de un
    solo servicio (con varios, el tiempo se reparte y no es exacto). Frente a la duración del catálogo, para ajustarla."""
    from citas.models import Config
    from citas.servicios import clave_cuenta, duracion_de

    atendidas = [c for c in citas if c.estado == c.Estado.ATENDIDA]
    por_atencion = Counter(clave_cuenta(c) for c in atendidas)
    cfg = Config.cargar()
    reales, catalogo = {}, {}
    for c in atendidas:
        if c.tiempo_real and por_atencion[clave_cuenta(c)] == 1:
            nombre = c.servicio.nombre_completo if c.servicio_id else (c.servicio_nombre or "Otro")
            reales.setdefault(nombre, []).append(c.minutos)
            catalogo[nombre] = duracion_de(c.servicio, cfg) if c.servicio_id else None
    salida = []
    for nombre, minutos in reales.items():
        real = round(sum(minutos) / len(minutos))
        cat = catalogo[nombre]
        salida.append({"servicio": nombre, "veces": len(minutos), "real": real, "minimo": min(minutos), "maximo": max(minutos),
                       "catalogo": cat, "diferencia": real - cat if cat else None})
    return sorted(salida, key=lambda x: (-x["veces"], x["servicio"]))


def de_negocio(desde, hasta):
    """El reporte con los módulos y funciones que usa el negocio."""
    from core.models import Ajustes
    from core.permisos import modulos_activos

    a = Ajustes.cargar()
    return reporte(desde, hasta, modulos_activos(a), comisiones=a.usa_comisiones, atendio=a.usa_atendio)


def de_persona(persona, desde, hasta):
    """La fila de una persona (para «Mi agenda»)."""
    r = de_negocio(desde, hasta)
    return next((f for f in r["filas"] if f["persona"] and f["persona"].pk == persona.pk), None), r["ver"]["comisiones"]
