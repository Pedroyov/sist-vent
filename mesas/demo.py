"""Mesas de ejemplo para el rubro restaurante (las usa python manage.py datos_demo).

Arma un salón, una terraza y una barra; dos mozos; dos semanas de mesas ya cobradas (con propinas, platos quitados,
cortesías y descuentos) y, para hoy, mesas ocupadas en distintos momentos: recién sentados, esperando cocina,
comiendo, pidiendo la cuenta y un pedido para llevar.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from productos.demo import opciones_demo
from productos.models import MovimientoStock, Variante
from productos.servicios import mover_stock

from .models import Cuenta, ItemCuenta, Mesa, Zona
from .servicios import abrir_cuenta, agregar, cobrar, cortesia, enviar_cocina, quitar

# Cómo pide una mesa típica: (categoría, probabilidad, unidades por persona)
PEDIDO = [("Entradas", .45, .4), ("Marinos", .35, .5), ("Platos de fondo", .7, .6), ("Pollos y parrillas", .5, .4),
          ("Sopas", .15, .3), ("Bebidas", .95, .8), ("Postres", .3, .5)]
MENU = [("Menú del día", 1, 1), ("Bebidas", .5, .5)]


def _mozos():
    User = get_user_model()
    mozos = [u for u in User.objects.filter(username="vendedor")]
    jorge, nuevo = User.objects.get_or_create(username="mozo", defaults={"first_name": "Jorge", "last_name": "Paredes Soto"})
    if nuevo:
        jorge.set_password("demo1234")
        jorge.save()
    jorge.groups.add(Group.objects.get(name="Vendedor"))
    return mozos + [jorge]


def _elegir(por_categoria, plan, personas, azar):
    items = []
    for cat, prob, por_persona in plan:
        vs = por_categoria.get(cat) or []
        if not vs or azar.random() > prob:
            continue
        unidades = max(1, round(personas * por_persona * azar.uniform(.6, 1.4)))
        for _ in range(min(unidades, 4)):
            v = azar.choice(vs)
            prev = next((i for i in items if i["variante"] == v.pk), None)
            if prev:
                prev["cantidad"] += 1
            else:
                items.append({"variante": v.pk, "cantidad": 1, "opciones": opciones_demo(v.producto, azar), "_v": v})
    return items


def _reponer(items):
    for i in items:
        v = i["_v"]
        if v.producto.maneja_stock:
            v.refresh_from_db(fields=["stock"])
            if v.stock - i["cantidad"] < 2:
                mover_stock(v, Decimal("48"), MovimientoStock.Tipo.INGRESO, nota="Compra a proveedor", costo_unitario=v.costo_efectivo,
                            referencia="Factura de ejemplo")


def _historial(mozos, por_categoria, dias=14):
    """Mesas ya cobradas: almuerzos y cenas de las últimas dos semanas (y el almuerzo de hoy)."""
    from ventas.models import Venta

    User = get_user_model()
    cajero = User.objects.filter(username="cajero").first()
    jefe = User.objects.filter(username="gerente").first() or cajero
    mesas = list(Mesa.objects.filter(activa=True))
    if not cajero or not mesas:
        return
    azar = random.Random(11)
    ahora = timezone.now()
    hoy = timezone.localdate()
    for d in range(dias - 1, -1, -1):
        dia = hoy - timedelta(days=d)
        finde = dia.weekday() >= 4
        turnos = [(12, 15, azar.randint(7, 11) + (4 if finde else 0)), (19, 22, azar.randint(4, 8) + (5 if finde else 0))]
        for desde, hasta, n in turnos:
            for _ in range(n):
                inicio = timezone.make_aware(timezone.datetime.combine(dia, timezone.datetime.min.time())) \
                    + timedelta(hours=azar.randint(desde, hasta - 1), minutes=azar.randint(0, 59))
                fin = inicio + timedelta(minutes=azar.randint(30, 95))
                if fin > ahora - timedelta(minutes=20):
                    continue
                personas = azar.choices([1, 2, 3, 4, 5, 6], weights=[10, 30, 20, 25, 8, 7])[0]
                menu = desde == 12 and dia.weekday() < 5 and azar.random() < .45
                mozo = azar.choice(mozos)
                llevar = azar.random() < .08
                c = abrir_cuenta(mozo, None if llevar else azar.choice(mesas), personas, nombre="Para llevar" if llevar else "")
                items = _elegir(por_categoria, MENU if menu else PEDIDO, personas, azar)
                if not items:
                    c.delete()
                    continue
                _reponer(items)
                agregar(c, [{k: v for k, v in i.items() if k != "_v"} for i in items], mozo)
                enviar_cocina(c)
                if azar.random() < .06 and c.items.filter(anulado=False).count() > 1:
                    quitar(c.items.first(), jefe, azar.choice(["El cliente cambió de pedido", "Demoró mucho", "Se equivocó el mozo"]),
                           puede_anular=True)
                if azar.random() < .07 and c.items.filter(anulado=False).count() > 1:
                    regalo = c.items.filter(anulado=False).last()
                    cortesia(regalo, jefe, azar.choice(["Plato salió mal", "Demora", "Cumpleaños", "Cliente frecuente"]), cantidad=1)
                total = c.total_por_cobrar
                descuento = Decimal("0")
                if azar.random() < .05 and total > 40:
                    descuento = (total * Decimal("0.1")).quantize(Decimal("1"))
                    total -= descuento
                propina = (total * Decimal("0.1")).quantize(Decimal("0.50")) if azar.random() < .35 else Decimal("0")
                metodo = azar.choices(["EFE", "YAP", "PLI", "TAR"], weights=[40, 30, 10, 20])[0]
                pago = total + propina
                if metodo == "EFE":
                    pago = next((Decimal(b) for b in (20, 50, 100, 200) if b >= pago and azar.random() < .5), pago)
                venta = cobrar(c, cajero, [{"metodo": metodo, "monto": str(pago)}], propina=propina, descuento=descuento,
                               descuento_motivo="Cliente frecuente" if descuento else "", descuento_por=jefe if descuento else None)
                Cuenta.objects.filter(pk=c.pk).update(abierta_en=inicio, cerrada_en=fin)
                ItemCuenta.objects.filter(cuenta=c).update(
                    creado=inicio + timedelta(minutes=3), enviado_en=inicio + timedelta(minutes=4),
                    listo_en=inicio + timedelta(minutes=azar.randint(12, 30)), servido_en=inicio + timedelta(minutes=azar.randint(31, 35)))
                cambios = {"fecha": fin}
                if d:  # las cajas de días pasados ya se cerraron: esas ventas no entran a ninguna
                    cambios["sesion_caja"] = None
                Venta.objects.filter(pk=venta.pk).update(**cambios)
                MovimientoStock.objects.filter(referencia=f"Venta {venta.numero_str}").update(fecha=fin)


def cargar_mesas():
    if Mesa.objects.exists():
        return Mesa.objects.count()
    salon, _ = Zona.objects.get_or_create(nombre="Salón", defaults={"orden": 10})
    terraza, _ = Zona.objects.get_or_create(nombre="Terraza", defaults={"orden": 20})
    barra, _ = Zona.objects.get_or_create(nombre="Barra", defaults={"orden": 30})
    for n in range(1, 11):
        Mesa.objects.create(zona=salon, nombre=str(n), capacidad=6 if n in (4, 8) else 4, orden=n)
    for n in range(1, 5):
        Mesa.objects.create(zona=terraza, nombre=f"T{n}", capacidad=2, orden=n)
    for n in range(1, 3):
        Mesa.objects.create(zona=barra, nombre=f"B{n}", capacidad=1, orden=n)

    mozos = _mozos()
    ana, jorge = mozos[0], mozos[-1]
    variantes = {v.nombre_completo: v for v in Variante.objects.filter(activa=True, producto__activo=True).select_related("producto", "producto__categoria")}
    por_categoria = {}
    for v in variantes.values():
        if v.producto.categoria and not v.producto.agotado:
            por_categoria.setdefault(v.producto.categoria.nombre, []).append(v)

    _historial(mozos, por_categoria)

    ahora = timezone.now()
    User = get_user_model()
    jefe = User.objects.filter(username="gerente").first()

    def mesa(nombre, mozo, personas, pedidos, minutos, enviar=True, nombre_cuenta=""):
        c = abrir_cuenta(mozo, Mesa.objects.get(nombre=nombre) if nombre else None, personas, nombre=nombre_cuenta)
        items = [{"variante": variantes[n].pk, "cantidad": cant, "nota": nota, "opciones": opciones_demo(variantes[n].producto)}
                 for n, cant, nota in pedidos if n in variantes]
        if items:
            agregar(c, items, mozo)
            if enviar:
                enviar_cocina(c)
        Cuenta.objects.filter(pk=c.pk).update(abierta_en=ahora - timedelta(minutes=minutos))
        c.items.update(creado=ahora - timedelta(minutes=max(minutos - 3, 0)),
                       **({"enviado_en": ahora - timedelta(minutes=max(minutos - 4, 0))} if enviar else {}))
        return c

    def servido(c, hace):
        c.items.filter(enviado_en__isnull=False).update(listo_en=ahora - timedelta(minutes=hace + 2), servido_en=ahora - timedelta(minutes=hace))

    # comiendo, con un plato ya listo esperando al mozo
    c = mesa("2", ana, 3, [("Pollo a la brasa · 1/2", 1, ""), ("Chicha morada · Jarra 1 L", 1, ""), ("Papa a la huancaína", 1, "sin aceituna")], 35)
    c.items.filter(descripcion__startswith="Chicha").update(listo_en=ahora - timedelta(minutes=2))
    # ya comieron y pidieron la cuenta
    c = mesa("5", ana, 2, [("Lomo saltado", 2, "uno sin cebolla"), ("Inca Kola 500 ml", 2, "")], 52)
    servido(c, 28)
    Cuenta.objects.filter(pk=c.pk).update(pidio_cuenta=True)
    # esperando cocina (marinos recién pedidos)
    mesa("3", jorge, 4, [("Ceviche · Mixto", 2, ""), ("Jalea mixta", 1, ""), ("Leche de tigre", 1, "bien helada"),
                         ("Cerveza Cusqueña 620 ml", 2, "")], 12)
    # familia grande: ya comieron, cumpleaños con postre de la casa
    c = mesa("8", jorge, 6, [("Combo familiar", 1, ""), ("Parrilla personal", 2, ""), ("Inca Kola 1.5 L", 2, ""),
                             ("Tequeños con guacamole", 1, "")], 70)
    servido(c, 40)
    agregar(c, [{"variante": variantes["Suspiro a la limeña"].pk, "cantidad": 3}, {"variante": variantes["Picarones"].pk, "cantidad": 1}], jorge)
    enviar_cocina(c)
    if jefe:
        cortesia(c.items.get(descripcion="Picarones"), jefe, "Cumpleaños")
    # pagaron por adelantado: la comida aún no sale de cocina (la mesa queda "Pagada" hasta que se vayan)
    cajero = User.objects.filter(username="cajero").first()
    c = mesa("6", ana, 2, [("Arroz chaufa · Pollo", 1, ""), ("Ají de gallina", 1, ""), ("Maracuyá · Jarra 1 L", 1, "")], 15)
    if cajero:
        cobrar(c, cajero, [{"metodo": "YAP", "monto": str(c.total_por_cobrar)}], liberar=False)
        c.items.filter(descripcion__startswith="Maracuyá").update(listo_en=ahora - timedelta(minutes=8), servido_en=ahora - timedelta(minutes=7))
    # recién se sentaron, aún no piden
    mesa("4", ana, 2, [], 2, enviar=False)
    # menú del día anotado, falta mandarlo a cocina
    mesa("T1", ana, 2, [("Menú ejecutivo", 2, ""), ("Limonada · Jarra 1 L", 1, "")], 4, enviar=False)
    # en la terraza, tomando algo
    c = mesa("T3", jorge, 2, [("Pisco sour", 2, ""), ("Anticuchos de corazón", 1, "")], 25)
    servido(c, 15)
    # barra
    c = mesa("B1", jorge, 1, [("Caldo de gallina", 1, ""), ("Infusión", 1, "manzanilla")], 18)
    # para llevar
    mesa(None, ana, 1, [("Pollo a la brasa · Entero", 1, ""), ("Inca Kola 1.5 L", 1, ""), ("Taper para llevar", 2, "")], 8,
         nombre_cuenta="Sra. Carla (llevar)")
    return Mesa.objects.count()
