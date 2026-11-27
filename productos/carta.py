"""Carta digital con QR: una página pública (sin usuario) con la carta del negocio.

Automática: categorías y productos activos marcados «mostrar en la carta», con su precio y variantes, lo agotado hoy y el
menú del día por tipo. O el PDF/foto que subió el negocio. Se enciende en Datos del negocio → Carta digital."""
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import cache_control

from core.models import Ajustes
from core.permisos import permiso_requerido


def contenido(excluir=()):
    """Las secciones de la carta automática: [(categoría, [productos con sus precios])]."""
    from django.db.models import Q

    from .models import Categoria, Producto

    productos = (Producto.objects.filter(activo=True, en_carta=True).exclude(tipo=Producto.Tipo.SERVICIO).exclude(pk__in=excluir)
                 .filter(Q(categoria__isnull=True) | Q(categoria__activa=True, categoria__en_carta=True))
                 .select_related("categoria").prefetch_related("variantes").order_by("nombre"))
    secciones, por_cat = [], {}
    for p in productos:
        vs = [v for v in p.variantes.all() if v.activa]
        p.precios = [(v.nombre, v.precio_venta) for v in vs if v.nombre] if len(vs) > 1 else []
        por_cat.setdefault(p.categoria_id, []).append(p)
    for c in Categoria.objects.filter(activa=True, en_carta=True).order_by("orden", "nombre"):
        if c.pk in por_cat:
            secciones.append((c.nombre, bloques(por_cat[c.pk])))
    if None in por_cat:
        secciones.append(("Otros", bloques(por_cat[None])))
    return secciones


MAX_COLUMNAS = 4  # más tamaños no entran en el celular: van uno por línea


def bloques(productos):
    """Agrupa en una tabla los platos de una sección que tienen los mismos tamaños (como en las cartas impresas):

        Ceviches         Personal  Mediano  Familiar
        De pescado          25.00    35.00     45.00
        Mixto               28.00    38.00     48.00

    Devuelve [{"cols": (tamaños,) o (), "productos": [...]}]: la tabla sale donde estaba su primer plato; el resto queda
    como siempre (precio a la derecha o cada variante en su línea). Cada plato de una tabla lleva `p.celdas`."""
    def clave(p):
        return tuple(n for n, _ in p.precios)

    cuantos = {}
    for p in productos:
        if 2 <= len(p.precios) <= MAX_COLUMNAS:
            cuantos[clave(p)] = cuantos.get(clave(p), 0) + 1
    salida, tablas = [], {}
    for p in productos:
        k = clave(p)
        if cuantos.get(k, 0) >= 2:
            p.celdas = [pr for _, pr in p.precios]
            if k not in tablas:
                tablas[k] = {"cols": k, "productos": []}
                salida.append(tablas[k])
            tablas[k]["productos"].append(p)
        elif salida and not salida[-1]["cols"]:
            salida[-1]["productos"].append(p)
        else:
            salida.append({"cols": (), "productos": [p]})
    return salida


@cache_control(max_age=60, public=True)
def carta(request):
    a = Ajustes.cargar()
    if a.carta == Ajustes.Carta.ARCHIVO and a.carta_archivo:
        return HttpResponseRedirect(a.carta_archivo.url)
    if a.carta != Ajustes.Carta.AUTOMATICA:
        raise Http404
    menu, en_menu = [], []
    if a.usa_menu:
        from .servicios import menu_tipos

        for t in menu_tipos():
            grupos = [(g.corto, [o for o in g.opciones.all() if o.activa]) for g in t.diarios if g.activo]
            grupos = [(n, ops) for n, ops in grupos if ops]
            if grupos:
                menu.append((t, grupos))
                en_menu.append(t.pk)  # ya sale arriba, en «Menú de hoy»
    return render(request, "productos/carta_publica.html", {"secciones": contenido(en_menu), "menu": menu, "negocio": a})


@permiso_requerido("config.negocio")
def carta_qr(request):
    """Hoja para imprimir: el QR de la carta en grande (y 4 chicos para recortar y poner en las mesas)."""
    from core.utils import qr_svg

    url = request.build_absolute_uri(reverse("carta"))
    return render(request, "productos/carta_qr.html", {"url": url, "qr": qr_svg(url, 260), "qr_chico": qr_svg(url, 150)})
