"""La cola de impresión. Ver impresion/models.py."""
from datetime import timedelta

from django.db import transaction
from django.urls import Resolver404, resolve
from django.utils import timezone

from .models import Estacion, Trabajo

SEGUNDOS_TOMADO = 60      # si la estación tomó un trabajo y no avisó, vuelve a la cola
SEGUNDOS_VIVA = 45        # una estación sin latido en este tiempo «no responde»
INTENTOS_MAX = 4
# Lo único que la estación puede imprimir: las mismas páginas de los botones «Imprimir».
IMPRIMIBLES = {"ventas:imprimir", "mesas:comanda", "mesas:precuenta", "caja:imprimir", "clientes:imprimir", "cobranzas:recibo"}


def activa():
    from core.models import Ajustes

    return Ajustes.cargar().imprimir_auto


def url_valida(url):
    url = str(url or "").strip()
    if not url.startswith("/") or url.startswith("//") or len(url) > 300:
        return False
    try:
        m = resolve(url.split("?")[0])
    except Resolver404:
        return False
    return f"{m.namespace}:{m.url_name}" in IMPRIMIBLES


def encolar(tipo, url, descripcion, usuario=None, copia=False, siempre=False):
    """Deja un trabajo en la cola (después de que se guarde lo que se imprime). Solo con la impresión automática
    encendida, salvo `siempre` (Imprimir → «Ticketera de caja»). Nunca falla la venta: si algo sale mal, no se encola."""
    if not (siempre or activa()) or not url_valida(url):
        return

    def crear():
        Trabajo.objects.create(tipo=tipo, url=url, descripcion=descripcion[:120], copia=copia,
                               creado_por=usuario if getattr(usuario, "pk", None) else None)

    transaction.on_commit(crear)


def tomar(estacion):
    """El siguiente trabajo para esta estación (o None). Cada trabajo lo toma una sola estación."""
    ahora = timezone.now()
    with transaction.atomic():
        vencidos = Trabajo.objects.filter(estado=Trabajo.Estado.TOMADO, tomado_en__lt=ahora - timedelta(seconds=SEGUNDOS_TOMADO))
        vencidos.update(estado=Trabajo.Estado.PENDIENTE)  # una estación que se apagó a medio imprimir
        t = (Trabajo.objects.select_for_update(skip_locked=True).filter(estado=Trabajo.Estado.PENDIENTE)
             .order_by("creado", "id").first())
        if t is None:
            return None
        t.estado, t.tomado_en, t.estacion, t.intentos = Trabajo.Estado.TOMADO, ahora, estacion, t.intentos + 1
        t.save(update_fields=["estado", "tomado_en", "estacion", "intentos"])
        return t


def terminar(trabajo_id, estacion, ok, error=""):
    t = Trabajo.objects.filter(pk=trabajo_id, estacion=estacion, estado=Trabajo.Estado.TOMADO).first()
    if not t:
        return None
    if ok:
        t.estado, t.impreso_en, t.error = Trabajo.Estado.IMPRESO, timezone.now(), ""
    else:
        t.error = str(error or "Error al imprimir")[:200]
        t.estado = Trabajo.Estado.ERROR if t.intentos >= INTENTOS_MAX else Trabajo.Estado.PENDIENTE
    t.save(update_fields=["estado", "impreso_en", "error"])
    return t


def latido(clave, usuario, nombre=""):
    e, _ = Estacion.objects.get_or_create(clave=str(clave)[:40], defaults={"usuario": usuario, "nombre": (nombre or "Caja")[:60]})
    e.ultimo_latido, e.usuario = timezone.now(), usuario
    if nombre:
        e.nombre = nombre[:60]
    e.save(update_fields=["ultimo_latido", "usuario", "nombre"])
    return e


def hay_estacion():
    return Estacion.objects.filter(ultimo_latido__gte=timezone.now() - timedelta(seconds=SEGUNDOS_VIVA)).exists()


def reimprimir(trabajo, usuario):
    return Trabajo.objects.create(tipo=trabajo.tipo, url=trabajo.url, descripcion=trabajo.descripcion, copia=True, creado_por=usuario)


def estado_cola():
    """Para avisos: cuántos esperan, cuántos fallaron y si hay estación."""
    desde = timezone.now() - timedelta(hours=12)
    qs = Trabajo.objects.filter(creado__gte=desde)
    return {"pendientes": qs.filter(estado__in=[Trabajo.Estado.PENDIENTE, Trabajo.Estado.TOMADO]).count(),
            "errores": qs.filter(estado=Trabajo.Estado.ERROR).count(), "estacion": hay_estacion()}
