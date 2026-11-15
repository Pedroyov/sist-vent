"""Comprobantes de ejemplo (modo prueba) para las ventas de ejemplo."""
import random

from django.contrib.auth import get_user_model


def cargar_comprobantes():
    from ventas.models import Venta

    from .models import Comprobante
    from .servicios import crear, enviar_seguro

    if Comprobante.objects.exists():
        return Comprobante.objects.count()
    azar = random.Random(5)
    usuario = get_user_model().objects.filter(username="cajero").first() or get_user_model().objects.first()
    empresas = [("20601234561", "INVERSIONES LOS ANDES S.A.C.", "Av. Arequipa 1450, Lince"),
                ("20512345671", "CONSTRUCTORA EL SOL E.I.R.L.", "Jr. Junín 320, Cercado de Lima")]
    from clientes.documentos import ruc_valido

    empresas = [(next(r[:10] + str(d) for d in range(10) if ruc_valido(r[:10] + str(d))), n, dir_) for r, n, dir_ in empresas]
    ventas = list(Venta.objects.filter(estado=Venta.Estado.PAGADA).order_by("fecha"))
    pendiente = None
    for v in ventas:
        if v.fiado or azar.random() > .7:
            continue  # unas se quedan con nota de venta
        if azar.random() < .12:
            ruc, nombre, dir_ = azar.choice(empresas)
            sol = {"tipo": "F", "doc": ruc, "nombre": nombre, "direccion": dir_}
        elif v.total > 700 or azar.random() < .2:
            sol = {"tipo": "B", "doc": f"4{azar.randint(1000000, 9999999)}", "nombre": azar.choice(["María Quispe", "José Huamán", "Rosa Mamani"]),
                   "direccion": ""}
        else:
            sol = {"tipo": "B", "doc": "", "nombre": "", "direccion": ""}
        try:
            c = crear(v, sol, usuario)
        except Exception:  # noqa: BLE001  (una venta que no se puede facturar se queda con nota de venta)
            continue
        pendiente = c
        enviar_seguro(c)
    if pendiente:  # el último queda sin enviar, para ver cómo se reenvía
        Comprobante.objects.filter(pk=pendiente.pk).update(estado=Comprobante.Estado.PENDIENTE, mensaje="Sin internet al cobrar (ejemplo).",
                                                         hash="", qr="")
    return Comprobante.objects.count()
