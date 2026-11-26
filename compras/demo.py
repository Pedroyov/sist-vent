"""Proveedores y compras de ejemplo (las usa python manage.py datos_demo en tienda, ropa, librería y restaurante).

Se registran con el mismo servicio que usa la pantalla, así el kardex, el costo promedio, los pagos y lo que se debe
quedan como en la vida real: una compra pagada fuera de caja, una al crédito ya vencida (con un pago a cuenta), otra que
vence esta semana y un flete como línea libre."""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Rubro

PROVEEDORES = {
    Rubro.TIENDA: [("Distribuidora El Sol", "Carlos Rojas"), ("Bebidas del Norte", "Lucía Ramos"), ("Mercado Mayorista Santa Anita", "")],
    Rubro.ROPA: [("Textiles Gamarra", "Rosa Quispe"), ("Confecciones Andinas", "Miguel Torres"), ("Accesorios Lima", "")],
    Rubro.LIBRERIA: [("Útiles Escolares Perú", "Ana Flores"), ("Papelera Central", "Jorge Díaz"), ("Editorial Arco", "")],
    Rubro.RESTAURANTE: [("Bebidas del Norte", "Lucía Ramos"), ("Avícola La Granja", "Pedro Huamán"), ("Gas Express", "")],
}


def _ruc(n):
    """Un RUC 20… de ejemplo con su dígito verificador correcto."""
    from clientes.documentos import PESOS_RUC

    base = f"20{n:08d}"
    resto = 11 - sum(int(d) * p for d, p in zip(base, PESOS_RUC)) % 11
    return base + str(0 if resto == 10 else 1 if resto == 11 else resto)


def _fechar(compra, dia):
    """La compra y su ingreso al kardex con la fecha de la factura (el servicio los registra «ahora»)."""
    from productos.models import MovimientoStock

    momento = timezone.make_aware(datetime.combine(dia, time(10, 30)))
    MovimientoStock.objects.filter(referencia=compra.referencia, tipo=MovimientoStock.Tipo.INGRESO).update(fecha=momento)


def cargar_compras(rubro):
    from productos.models import Variante

    from .models import Compra, Proveedor
    from .servicios import pagar, registrar_compra

    if rubro not in PROVEEDORES or Compra.objects.exists():
        return 0
    azar = random.Random(7)
    admin = get_user_model().objects.get(username="admin")
    variantes = list(Variante.objects.filter(activa=True, producto__activo=True, producto__maneja_stock=True)
                     .select_related("producto").order_by("producto__nombre", "orden"))
    if not variantes:
        return 0
    hoy = timezone.localdate()
    provs = []
    for i, (nombre, contacto) in enumerate(PROVEEDORES[rubro]):
        provs.append(Proveedor.objects.create(
            nombre=f"{nombre.upper()} S.A.C.", comercial=nombre, ruc=_ruc(1234500 + i * 37), contacto=contacto,
            telefono=f"98765{4320 + i}" if contacto else "", plazo=15 if i < 2 else 0))
    if rubro == Rubro.RESTAURANTE:
        return _compras_restaurante(admin, provs, variantes, hoy)
    azar.shuffle(variantes)
    tercio = max(1, len(variantes) // 3)
    grupos = [variantes[:tercio], variantes[tercio:2 * tercio], variantes[2 * tercio:]]

    def lineas(vs, k):
        salida = []
        for v in vs[:k]:
            costo = v.costo_efectivo or (v.precio_venta * Decimal("0.6")).quantize(Decimal("0.10"))
            cantidad = Decimal("10") if v.producto.fraccionable else Decimal(azar.choice([6, 12, 12, 24]))
            salida.append({"variante": v.pk, "cantidad": str(cantidad), "costo": str(costo)})
        return salida

    n = 0
    plan = [  # (proveedor, días atrás, crédito, número)
        (0, 24, False, 812), (1, 20, True, 1450), (0, 10, True, 845), (2, 4, False, 2231), (1, 2, True, 1497),
    ]
    for prov_i, atras, credito, numero in plan:
        p, vs = provs[prov_i], grupos[prov_i]
        if not vs:
            continue
        dia = hoy - timedelta(days=atras)
        items = lineas(vs, azar.randint(3, 6))
        if prov_i == 0 and not credito:
            items.append({"variante": None, "descripcion": "Flete", "cantidad": "1", "costo": "15"})
        documento = "BOL" if prov_i == 2 else "FAC"
        c = registrar_compra(admin, p, items, documento, "B001" if documento == "BOL" else "F001", str(numero),
                             dia, credito=credito, pago=None if credito else "fuera")
        _fechar(c, dia)
        if credito and atras >= 20:  # la vencida tiene un pago a cuenta
            pagar(c, (c.total / 2).quantize(Decimal("0.10")), admin, "fuera", dia + timedelta(days=7))
        n += 1
    return n


def _compras_restaurante(admin, provs, variantes, hoy):
    """Un restaurante compra bebidas (con stock) a la distribuidora, pollo y gas como insumos (líneas libres) y las
    verduras en el mercado, sin proveedor registrado («Proveedor varios»)."""
    from .servicios import pagar, registrar_compra

    bebidas, pollo, gas = provs
    plan = [  # (proveedor, días atrás, crédito, número, líneas)
        (bebidas, 22, True, 3301, [{"variante": v.pk, "cantidad": "24", "costo": str(v.costo_efectivo or (v.precio_venta * Decimal("0.55")).quantize(Decimal("0.10")))}
                                   for v in variantes[:6]]),
        (pollo, 6, True, 518, [{"variante": None, "descripcion": "Pollo entero (kg)", "cantidad": "40", "costo": "9.80"}]),
        (gas, 3, False, 92, [{"variante": None, "descripcion": "Balón de gas 45 kg", "cantidad": "1", "costo": "210"}]),
        (None, 1, False, "", [{"variante": None, "descripcion": "Verduras del mercado", "cantidad": "1", "costo": "86.50"},
                              {"variante": None, "descripcion": "Limones (malla)", "cantidad": "1", "costo": "38"}]),
        (bebidas, 2, False, 3342, [{"variante": v.pk, "cantidad": "12", "costo": str(v.costo_efectivo or (v.precio_venta * Decimal("0.55")).quantize(Decimal("0.10")))}
                                   for v in variantes[:3]]),
    ]
    n = 0
    for prov, atras, credito, numero, items in plan:
        if not items:
            continue
        dia = hoy - timedelta(days=atras)
        documento = "SIN" if prov is None else ("BOL" if prov is gas else "FAC")
        c = registrar_compra(admin, prov, items, documento, "" if documento == "SIN" else ("B001" if documento == "BOL" else "F001"),
                             str(numero), dia, credito=credito, pago=None if credito else "fuera")
        _fechar(c, dia)
        if credito and atras >= 20:  # la vencida tiene un pago a cuenta
            pagar(c, (c.total / 2).quantize(Decimal("0.10")), admin, "fuera", dia + timedelta(days=7))
        n += 1
    return n
