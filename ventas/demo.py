"""Ventas de ejemplo de los últimos días (las usa python manage.py datos_demo)."""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from productos.demo import opciones_demo
from productos.models import MovimientoStock, Opcion, Variante
from productos.servicios import mover_stock

from .models import MetodoPago, Venta
from .servicios import registrar_venta


def cargar_ventas(dias=7, por_dia=(6, 14)):
    if Venta.objects.exists():
        return Venta.objects.count()
    azar = random.Random(42)
    User = get_user_model()
    vendedores = list(User.objects.filter(username__in=["cajero", "vendedor", "gerente"])) or list(User.objects.all()[:1])
    variantes = list(Variante.objects.filter(activa=True, producto__activo=True).select_related("producto"))
    if not variantes or not vendedores:
        return 0
    from caja.models import MovimientoCaja, SesionCaja
    from caja.servicios import abrir, calcular, cerrar, movimiento

    hoy = timezone.localdate()
    for d in range(dias - 1, -1, -1):
        dia = hoy - timedelta(days=d)
        apertura = timezone.make_aware(datetime.combine(dia, time(7, 55)))
        cajas = []
        for u in vendedores:
            s = SesionCaja.abierta_de(u) or abrir(u, Decimal(azar.choice([50, 100, 100, 150])))
            SesionCaja.objects.filter(pk=s.pk).update(abierta_en=apertura)
            cajas.append(s)
        if azar.random() < .6:
            m = movimiento(cajas[0], MovimientoCaja.Tipo.EGRESO, Decimal(azar.choice([25, 40, 60, 85])), "Pago a proveedor de bebidas",
                           cajas[0].usuario, MovimientoCaja.Categoria.PROVEEDOR)
            MovimientoCaja.objects.filter(pk=m.pk).update(fecha=apertura + timedelta(hours=3))
        horas = sorted(time(azar.randint(8, 20), azar.randint(0, 59)) for _ in range(azar.randint(*por_dia)))
        for hora in horas:
            fecha = timezone.make_aware(datetime.combine(dia, hora))
            if fecha > timezone.now():
                break
            elegidas = azar.sample(variantes, k=min(len(variantes), azar.choice([1, 1, 2, 2, 3, 4])))
            items = [{"variante": v.pk, "cantidad": str(azar.choice([1, 1, 1, 2, 3]) if not v.producto.fraccionable
                                                          else Decimal(azar.choice(["0.5", "1", "1.5", "2"]))),
                      "opciones": opciones_demo(v.producto, azar)} for v in elegidas]
            for v, i in zip(elegidas, items):  # reponer antes de quedarse sin stock, como haría la tienda
                v.refresh_from_db(fields=["stock"])
                if v.producto.maneja_stock and v.stock - Decimal(i["cantidad"]) < 1:
                    mov = mover_stock(v, Decimal("24"), MovimientoStock.Tipo.INGRESO, nota="Compra a proveedor",
                                      costo_unitario=v.costo_efectivo, referencia="Factura de ejemplo")
                    MovimientoStock.objects.filter(pk=mov.pk).update(fecha=fecha - timedelta(minutes=30))
            total = sum((v.precio_venta + sum((o.precio for o in Opcion.objects.filter(pk__in=i["opciones"])), Decimal(0)))
                        * Decimal(i["cantidad"]) for v, i in zip(elegidas, items))
            metodo = azar.choices(["EFE", "YAP", "PLI", "TAR"], weights=[55, 25, 10, 10])[0]
            monto = total
            if metodo == MetodoPago.EFECTIVO:
                monto = next((Decimal(b) for b in (10, 20, 50, 100, 200) if b >= total and azar.random() < .6), total)
            venta = registrar_venta(azar.choice(vendedores), items, [{"metodo": metodo, "monto": str(monto.quantize(Decimal("0.01")))}])
            Venta.objects.filter(pk=venta.pk).update(fecha=fecha)
            MovimientoStock.objects.filter(referencia=f"Venta {venta.numero_str}").update(fecha=fecha)
        if d > 0:  # los días pasados se cerraron; hoy las cajas siguen abiertas
            for s in cajas:
                esperado = calcular(s)["esperado"]
                diferencia = Decimal(azar.choice(["0", "0", "0", "0", "-0.50", "1.00", "-2.00"]))
                cerrar(s, esperado + diferencia, s.usuario, nota="" if not diferencia else "Diferencia de ejemplo")
                SesionCaja.objects.filter(pk=s.pk).update(cerrada_en=timezone.make_aware(datetime.combine(dia, time(21, 10))))
    return Venta.objects.count()
