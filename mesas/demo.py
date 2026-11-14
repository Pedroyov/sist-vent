"""Mesas de ejemplo para el rubro restaurante (las usa python manage.py datos_demo)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from productos.demo import opciones_demo
from productos.models import Variante

from .models import Cuenta, Mesa, Zona
from .servicios import abrir_cuenta, agregar, enviar_cocina


def _historial(mozo, variantes):
    """Mesas ya cobradas en los últimos días (para que los reportes de mesas tengan datos)."""
    import random
    from decimal import Decimal

    from ventas.models import Venta

    from .models import ItemCuenta
    from .servicios import cobrar, cortesia, quitar

    User = get_user_model()
    cajero = User.objects.filter(username="cajero").first()
    jefe = User.objects.filter(username="gerente").first() or User.objects.filter(is_superuser=True).first() or cajero
    platos = [v for v in variantes.values() if v.producto.activo and not v.producto.maneja_stock]
    if not cajero or not platos:
        return
    azar = random.Random(11)
    mesas = list(Mesa.objects.all())
    hoy = timezone.localdate()
    for d in range(6, 0, -1):
        for _ in range(azar.randint(4, 8)):
            inicio = timezone.make_aware(timezone.datetime.combine(hoy - timedelta(days=d), timezone.datetime.min.time())) \
                + timedelta(hours=azar.randint(12, 21), minutes=azar.randint(0, 59))
            c = abrir_cuenta(mozo, azar.choice(mesas), azar.randint(1, 5))
            elegidos = azar.sample(platos, k=min(len(platos), azar.randint(2, 4)))
            agregar(c, [{"variante": v.pk, "cantidad": azar.choice([1, 1, 2]), "opciones": opciones_demo(v.producto, azar)} for v in elegidos], mozo)
            enviar_cocina(c)
            if azar.random() < .12:
                quitar(c.items.first(), cajero, azar.choice(["El cliente cambió de pedido", "Demoró mucho", "Se equivocó el mozo"]),
                       puede_anular=True)
            if azar.random() < .1:
                regalo = c.items.filter(anulado=False).last()
                cortesia(regalo, jefe, azar.choice(["Plato salió mal", "Demora", "Cumpleaños", "Cliente frecuente"]), cantidad=1)
            total = c.total_por_cobrar
            descuento = Decimal("0")
            if azar.random() < .08 and total > 20:
                descuento = (total * Decimal("0.1")).quantize(Decimal("1"))
                total -= descuento
            propina = (total * Decimal("0.1")).quantize(Decimal("0.50")) if azar.random() < .4 else Decimal("0")
            venta = cobrar(c, cajero, [{"metodo": azar.choice(["EFE", "EFE", "YAP", "TAR"]), "monto": str(total + propina)}], propina=propina,
                           descuento=descuento, descuento_motivo="Cliente frecuente" if descuento else "", descuento_por=jefe if descuento else None)
            fin = inicio + timedelta(minutes=azar.randint(30, 95))
            Cuenta.objects.filter(pk=c.pk).update(abierta_en=inicio, cerrada_en=fin)
            ItemCuenta.objects.filter(cuenta=c).update(creado=inicio + timedelta(minutes=3), enviado_en=inicio + timedelta(minutes=4),
                                                      listo_en=inicio + timedelta(minutes=20), servido_en=inicio + timedelta(minutes=22))
            Venta.objects.filter(pk=venta.pk).update(fecha=fin, sesion_caja=None)


def cargar_mesas():
    if Mesa.objects.exists():
        return Mesa.objects.count()
    salon, _ = Zona.objects.get_or_create(nombre="Salón", defaults={"orden": 10})
    terraza, _ = Zona.objects.get_or_create(nombre="Terraza", defaults={"orden": 20})
    for n in range(1, 9):
        Mesa.objects.create(zona=salon, nombre=str(n), capacidad=6 if n in (4, 8) else 4, orden=n)
    for n in range(1, 5):
        Mesa.objects.create(zona=terraza, nombre=f"T{n}", capacidad=2, orden=n)

    User = get_user_model()
    mozo = User.objects.filter(username="vendedor").first() or User.objects.first()
    variantes = {v.nombre_completo: v for v in Variante.objects.filter(activa=True).select_related("producto")}

    def pedir(cuenta, pedidos, enviar=True, minutos=0):
        items = [{"variante": variantes[n].pk, "cantidad": c, "nota": nota, "opciones": opciones_demo(variantes[n].producto)}
                 for n, c, nota in pedidos if n in variantes]
        if items:
            agregar(cuenta, items, mozo)
            if enviar:
                enviar_cocina(cuenta)
        Cuenta.objects.filter(pk=cuenta.pk).update(abierta_en=timezone.now() - timedelta(minutes=minutos))

    _historial(mozo, variantes)

    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="2"), 3)
    pedir(c, [("Pollo a la brasa · 1/2", 1, ""), ("Chicha morada · Jarra 1 L", 1, ""), ("Papa a la huancaína", 1, "sin aceituna")], minutos=35)
    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="5"), 2)
    pedir(c, [("Lomo saltado", 2, "uno sin cebolla"), ("Inca Kola 500 ml", 2, "")], minutos=52)
    Cuenta.objects.filter(pk=c.pk).update(pidio_cuenta=True)
    c.items.update(listo_en=timezone.now() - timedelta(minutes=30), servido_en=timezone.now() - timedelta(minutes=28))
    c2 = Cuenta.objects.get(mesa__nombre="2", estado=Cuenta.Estado.ABIERTA)
    c2.items.filter(descripcion__startswith="Chicha").update(listo_en=timezone.now() - timedelta(minutes=2))
    c = abrir_cuenta(mozo, Mesa.objects.get(nombre="T1"), 2)
    pedir(c, [("Menú ejecutivo", 2, "")], enviar=False, minutos=4)
    return Mesa.objects.count()
