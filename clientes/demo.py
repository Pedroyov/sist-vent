"""Clientes de ejemplo con fiados y pagos (los usa python manage.py datos_demo)."""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from productos.models import MovimientoStock, Variante
from ventas.models import Venta

from .models import Abono, Cliente
from .servicios import registrar_abono

CLIENTES = [
    ("DNI", "45123678", "María Quispe Rojas", "987111222", Decimal("200")),
    ("DNI", "40987654", "José Huamán Torres", "986333444", Decimal("150")),
    ("DNI", "72345611", "Rosa Mamani Cruz", "985555666", Decimal("0")),
    ("DNI", "41239876", "Carlos Díaz Paredes", "", Decimal("100")),
    ("RUC", "20601234560", "Inversiones Los Andes S.A.C.", "014445566", Decimal("0")),
    ("SD", "", "Doña Juana (vecina)", "984777888", Decimal("80")),
]


def cargar_clientes():
    from ventas.servicios import registrar_venta

    if Cliente.objects.exists():
        return Cliente.objects.count()
    from .documentos import ruc_valido

    clientes = []
    for tipo, num, nombre, tel, limite in CLIENTES:
        if tipo == "RUC" and not ruc_valido(num):  # busca un RUC de ejemplo válido
            num = next(f"2060123456{d}" for d in range(10) if ruc_valido(f"2060123456{d}"))
        clientes.append(Cliente.objects.create(tipo_documento=tipo, numero_documento=num, nombre=nombre, telefono=tel, limite_credito=limite))
    User = get_user_model()
    cajero = User.objects.filter(username="cajero").first()
    variantes = list(Variante.objects.filter(activa=True, producto__activo=True).select_related("producto"))
    if not cajero or not variantes:
        return len(clientes)
    azar = random.Random(7)
    ahora = timezone.now()
    for c in clientes[:4] + clientes[5:]:
        for dias in sorted(azar.sample(range(1, 7), 2), reverse=True):
            vs = azar.sample(variantes, 2)
            from productos.demo import opciones_demo
            from productos.models import Opcion

            items = [{"variante": v.pk, "cantidad": "1", "opciones": opciones_demo(v.producto)} for v in vs]
            total = sum(v.precio_venta + sum((o.precio for o in Opcion.objects.filter(pk__in=i["opciones"])), Decimal(0))
                        for v, i in zip(vs, items))
            try:
                venta = registrar_venta(cajero, items, [{"metodo": "CRE", "monto": str(total)}], cliente_id=c.pk,
                                        puede_fiar=True, puede_exceder_limite=True)
            except Exception:  # sin caja abierta u otro motivo: la demo sigue
                continue
            fecha = ahora - timedelta(days=dias, hours=azar.randint(1, 8))
            Venta.objects.filter(pk=venta.pk).update(fecha=fecha, sesion_caja=None)
            MovimientoStock.objects.filter(referencia=f"Venta {venta.numero_str}").update(fecha=fecha)
    for c in clientes[:2]:  # algunos ya pagaron una parte
        saldo = c.saldo
        if saldo > 0:
            a = registrar_abono(c, (saldo / 2).quantize(Decimal("0.10")), "EFE", cajero, "Pago a cuenta")
            Abono.objects.filter(pk=a.pk).update(fecha=ahora - timedelta(days=1))
    return len(clientes)
