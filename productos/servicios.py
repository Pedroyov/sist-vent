"""Operaciones de stock. Toda entrada o salida pasa por aquí (también las ventas, cuando existan)."""
from decimal import Decimal

from django.db import transaction

from .models import CERO, MovimientoStock, Variante

T = MovimientoStock.Tipo


def mover_stock(variante, cantidad, tipo, usuario=None, nota="", costo_unitario=None, referencia=""):
    """Suma (o resta, si es negativa) la cantidad al stock y lo anota en el kardex.
    El stock puede quedar negativo: es mejor dejar vender y corregir con un conteo que trabar la caja.
    Un ingreso con costo actualiza el costo por promedio ponderado (lo que ya había a su costo + lo que entra al suyo)."""
    cantidad = Decimal(cantidad)
    with transaction.atomic():
        v = Variante.objects.select_for_update().select_related("producto").get(pk=variante.pk)
        previo = v.stock
        v.stock += cantidad
        campos = ["stock"]
        if costo_unitario is not None and tipo in (T.INGRESO, T.INICIAL):
            v.costo = costo_promedio(previo, v.costo if v.costo is not None else v.producto.costo, cantidad, Decimal(costo_unitario))
            campos.append("costo")
        v.save(update_fields=campos)
        mov = MovimientoStock.objects.create(
            variante=v, tipo=tipo, cantidad=cantidad, saldo=v.stock, costo_unitario=costo_unitario,
            nota=nota[:200], referencia=referencia[:60], usuario=usuario,
        )
    variante.stock = v.stock
    if "costo" in campos:
        variante.costo = v.costo
    return mov


def costo_promedio(stock, costo, cantidad, costo_nuevo):
    """Promedio ponderado: (stock × costo + cantidad × costo nuevo) ÷ (stock + cantidad). Sin stock positivo o sin costo
    anterior, manda el costo nuevo (lo que había no tiene valor que promediar)."""
    if costo is None or stock <= 0 or cantidad <= 0:
        return costo_nuevo
    return ((stock * costo + cantidad * costo_nuevo) / (stock + cantidad)).quantize(Decimal("0.01"))


def por_reponer():
    """Variantes con stock en el mínimo o debajo (solo productos activos que controlan stock)."""
    from django.db.models import F

    return Variante.objects.filter(activa=True, producto__activo=True, producto__maneja_stock=True,
                                   stock__lte=F("producto__stock_minimo"))


def ajustar_a(variante, conteo, usuario=None, nota=""):
    """Deja el stock igual al conteo físico. Devuelve el movimiento o None si ya coincidía."""
    with transaction.atomic():
        v = Variante.objects.select_for_update().get(pk=variante.pk)
        diferencia = Decimal(conteo) - v.stock
        if diferencia == 0:
            return None
        return mover_stock(v, diferencia, T.AJUSTE, usuario, nota or "Conteo de inventario")


def separar(texto):
    """'S, M ,L' -> ['S', 'M', 'L'] sin repetidos ni vacíos."""
    vistos, salida = set(), []
    for parte in (texto or "").replace(";", ",").split(","):
        p = " ".join(parte.split())
        if p and p.lower() not in vistos:
            vistos.add(p.lower())
            salida.append(p)
    return salida


def generar_variantes(producto, opciones1, opciones2=None):
    """Crea las combinaciones (S/Rojo, S/Azul, M/Rojo…). Devuelve (creadas, ya_existían).
    La variante sin nombre del producto se retira (si no tiene stock), porque desde ahora se vende por variante."""
    a, b = separar(opciones1), separar(opciones2)
    nombres = [f"{x} / {y}" for x in a for y in b] if b else a
    if not nombres:
        return 0, 0
    with transaction.atomic():
        unica = producto.variante_unica()
        if unica:
            if unica.stock != CERO:
                raise ValueError("El producto todavía tiene stock sin talla/opción. Ajusta ese stock a 0 antes de crear variantes.")
            if en_uso(unica):
                unica.activa = False
                unica.codigo = ""
                unica.save(update_fields=["activa", "codigo"])
                unica.nombre = f"(sin variante {unica.pk})"
                unica.save(update_fields=["nombre"])
            else:
                unica.delete()
        orden = (producto.variantes.order_by("-orden").values_list("orden", flat=True).first() or 0) + 1
        existentes = {n.lower() for n in producto.variantes.values_list("nombre", flat=True)}
        creadas = 0
        for n in nombres:
            if n.lower() in existentes:
                continue
            Variante.objects.create(producto=producto, nombre=n, orden=orden)
            orden += 1
            creadas += 1
    return creadas, len(nombres) - creadas


def asegurar_variante_unica(producto):
    """Un producto sin variantes con nombre necesita su variante sin nombre para vender y contar stock."""
    if not producto.variantes.filter(activa=True).exists():
        v = producto.variante_unica()
        if v:
            v.activa = True
            v.save(update_fields=["activa"])
            return v
        return Variante.objects.create(producto=producto, nombre="")
    return producto.variante_unica()


# --- Opciones al pedir y agotados ---------------------------------------------------

class OpcionInvalida(Exception):
    pass


def foto_combo(producto):
    """Lo que trae un combo, tal como se guarda en el pedido y la venta (marcado "c"): la cocina lo ve, el ticket no,
    y al vender se descuenta su stock aunque después cambie el combo."""
    if not producto.es_combo:
        return []
    foto = []
    for i in producto.combo_items.select_related("variante__producto"):
        q = i.cantidad.normalize()
        foto.append({"id": f"k{i.pk}", "g": "Combo", "n": (f"{q} " if q != 1 else "") + i.variante.nombre_completo, "p": "0",
                     "c": True, "v": i.variante_id, "q": str(i.cantidad)})
    return foto


def consumo(variante, cantidad, foto):
    """Qué stock se mueve al vender `cantidad` de esta variante con estas opciones: [(variante, cantidad)].
    El producto mismo (si se cuenta), lo que trae el combo y las opciones que descuentan de otro producto."""
    from .models import Variante

    salidas = {}
    if variante.producto.maneja_stock:
        salidas[variante.pk] = cantidad
    for o in foto or []:
        if o.get("v"):
            salidas[o["v"]] = salidas.get(o["v"], Decimal("0")) + Decimal(str(o.get("q") or 1)) * cantidad
    if not salidas:
        return []
    vs = Variante.objects.select_related("producto").in_bulk(list(salidas))
    return [(vs[k], q) for k, q in salidas.items() if k in vs and vs[k].producto.maneja_stock]


def resolver_opciones(producto, ids, revisar_disponible=True):
    """Valida las opciones elegidas para un producto. Devuelve (foto, precio_extra, texto):
    foto = [{"id", "g", "n", "p"}] tal como se guarda en la venta o el pedido."""
    from .models import GrupoOpciones, Opcion

    from core.models import Ajustes

    ajustes = Ajustes.cargar()
    combo = foto_combo(producto)
    if not ajustes.usa_opciones and not producto.es_combo:  # pedidos simples: sin opciones (salvo lo que se elige en un combo)
        return combo, Decimal("0"), ""
    # "s12" = quitar el componente 12 ("SIN ENSALADA"); el resto son opciones
    try:
        crudos = list(ids or [])
        sin_ids = sorted({int(str(i)[1:]) for i in crudos if str(i).startswith("s")})
        ids = sorted({int(i) for i in crudos if not str(i).startswith("s")})
    except (TypeError, ValueError):
        raise OpcionInvalida("Opción no válida.")
    if not ajustes.usa_lleva:
        sin_ids = []
    grupos = ordenar_grupos(producto.grupos.filter(activo=True).prefetch_related("opciones"))
    validas = {o.pk: o for g in grupos for o in g.opciones.all() if o.activa}
    elegidas = []
    for i in ids:
        o = validas.get(i)
        if o is None:
            raise OpcionInvalida(f"Una de las opciones ya no está disponible para {producto.nombre}. Recarga la página.")
        if revisar_disponible and o.agotada:
            raise OpcionInvalida(f"«{o.nombre}» está agotado hoy.")
        elegidas.append(o)
    for g in grupos:
        n = sum(1 for o in elegidas if o.grupo_id == g.pk)
        if not n and g.minimo:  # obligatorio sin elegir: va lo que viene incluido, si hay
            incluidas = [o for o in g.opciones.all() if o.activa and o.por_defecto and not (revisar_disponible and o.agotada)]
            elegidas += incluidas[:g.minimo]
            n = len(incluidas[:g.minimo])
        if n < minimo_disponible(g, revisar_disponible):
            raise OpcionInvalida(f"{producto.nombre}: elige {g.nombre.lower()}.")
        if g.maximo and n > g.maximo:
            raise OpcionInvalida(f"{producto.nombre}: en {g.nombre.lower()} se puede elegir hasta {g.maximo}.")
    orden = {g.pk: i for i, g in enumerate(grupos)}
    elegidas.sort(key=lambda o: (orden[o.grupo_id], o.orden, o.pk))
    foto = combo + [dict({"id": o.pk, "g": o.grupo.nombre, "n": o.nombre, "p": str(o.precio)}, **({"v": o.variante_id} if o.variante_id else {}))
                    for o in elegidas]
    if sin_ids:
        quitables = {c.pk: c for c in producto.componentes.all() if c.quitable}
        for i in sin_ids:
            c = quitables.get(i)
            if c is None:
                raise OpcionInvalida(f"{producto.nombre}: eso no se puede quitar. Recarga la página.")
            foto.append({"id": f"s{c.pk}", "g": "Sin", "n": f"SIN {c.nombre.upper()}", "p": "0", "sin": True})
    return foto, sum((o.precio for o in elegidas), Decimal("0")), texto_opciones(foto)


def en_uso(objeto):
    """¿Algún registro del sistema (venta, movimiento, pedido de mesa, comprobante…) apunta a este objeto?
    Se revisa de forma genérica para que productos no dependa de los módulos que lo usan."""
    for rel in objeto._meta.get_fields(include_hidden=True):
        if (rel.one_to_many or rel.one_to_one) and rel.auto_created and not rel.concrete:
            if rel.related_model._base_manager.filter(**{rel.field.name: objeto}).exists():
                return True
    return False


def leer_linea_opcion(linea):
    """«Papas fritas *» o «Huevo frito | 2.00» -> (nombre, precio, viene_incluida). Lanza ValueError si el precio no sirve."""
    import re

    nombre, _, precio = str(linea).partition("|")
    nombre = nombre.strip()
    defecto = nombre.startswith("*") or nombre.endswith("*")
    nombre = " ".join(nombre.strip("* ").split())[:60]
    precio = re.sub(r"[^\d.,*]", "", precio)
    defecto = defecto or "*" in precio
    precio = precio.replace("*", "").replace(",", ".")
    try:
        precio = Decimal(precio) if precio else Decimal("0")
    except ArithmeticError:
        raise ValueError("el precio no es un número")
    if not precio.is_finite() or precio < 0:
        raise ValueError("el precio no es válido")
    return nombre, precio.quantize(Decimal("0.01")), defecto


def minimo_disponible(grupo, revisar_disponible=True):
    """Lo obligatorio no puede trabar el pedido: si hoy hay menos opciones que el mínimo (todas agotadas, o el menú
    no trae entradas), se pide solo lo que hay."""
    hay = sum(1 for o in grupo.opciones.all() if o.activa and not (revisar_disponible and o.agotada))
    return min(grupo.minimo, hay)


def ordenar_grupos(grupos):
    """Primero lo obligatorio (término, acompañamiento) y luego lo opcional (adicionales, cremas)."""
    return sorted(grupos, key=lambda g: (0 if g.minimo else 1, g.orden, g.nombre))


def texto_opciones(foto):
    return ", ".join(o["n"] + (f" +{Decimal(o['p']):.2f}" if Decimal(o.get("p") or 0) else "") for o in foto or [] if not o.get("c"))


def descripcion_con_opciones(nombre, foto):
    t = ", ".join(o["n"] for o in foto or [] if not o.get("c"))
    return f"{nombre} ({t})" if t else nombre


def marcar_agotado(objeto, agotado=True):
    """Producto u opción: agotado por hoy (o disponible de nuevo)."""
    from django.utils import timezone

    campo = "agotado_en" if hasattr(objeto, "agotado_en") else "agotada_en"
    setattr(objeto, campo, timezone.now() if agotado else None)
    objeto.save(update_fields=[campo])


# --- Menú del día ------------------------------------------------------------------
# El menú es un producto normal ("Menú ejecutivo", precio fijo) con grupos de opciones marcados "cambia cada día"
# ("Entrada", "Segundo"). Cada mañana se activan las opciones de hoy; las de otros días quedan guardadas (inactivas)
# para volver a ponerlas con un toque.

def menu_crear():
    """Crea los grupos Entrada y Segundo (si no hay ninguno diario) y los pone en los productos de la categoría del menú."""
    from .models import GrupoOpciones, Producto

    if GrupoOpciones.objects.filter(diario=True).exists():
        return list(GrupoOpciones.objects.filter(diario=True))
    base = (GrupoOpciones.objects.order_by("-orden").values_list("orden", flat=True).first() or 0) + 10
    grupos = []
    for i, nombre in enumerate(["Entrada", "Segundo"]):
        g, _ = GrupoOpciones.objects.get_or_create(nombre=nombre, defaults={"minimo": 1, "maximo": 1, "orden": base + i})
        g.diario, g.activo = True, True
        g.save(update_fields=["diario", "activo"])
        grupos.append(g)
    for p in Producto.objects.filter(activo=True, categoria__nombre__iregex=r"men[uú]"):
        p.grupos.add(*grupos)
    return grupos


def menu_agregar(grupo, nombre, precio=None):
    """Pone un plato en el menú de hoy: si ya se sirvió otro día, lo vuelve a activar."""
    from .models import Opcion

    nombre = " ".join(str(nombre or "").split())[:60]
    if not nombre:
        raise ValueError("Escribe el nombre del plato.")
    try:
        precio = Decimal(str(precio).replace(",", ".")) if str(precio or "").strip() else None
    except ArithmeticError:
        raise ValueError("Precio no válido.")
    if precio is not None and (not precio.is_finite() or precio < 0 or precio > 9999):
        raise ValueError("Precio no válido.")
    o = Opcion.objects.filter(grupo=grupo, nombre__iexact=nombre).first()
    if o is None:
        orden = (grupo.opciones.order_by("-orden").values_list("orden", flat=True).first() or 0) + 1
        o = Opcion(grupo=grupo, nombre=nombre, orden=orden)
    o.activa, o.agotada_en = True, None
    if precio is not None or o.pk is None:
        o.precio = (precio or Decimal("0")).quantize(Decimal("0.01"))
    o.save()
    return o


def menu_limpiar():
    """Empieza el menú de cero (los platos quedan guardados para volver a usarlos)."""
    from .models import Opcion

    return Opcion.objects.filter(grupo__diario=True, activa=True).update(activa=False, agotada_en=None)


def menu_texto(nombre_negocio=""):
    """El menú de hoy listo para pegar en WhatsApp."""
    from django.utils import timezone
    from django.utils.formats import date_format

    from .models import GrupoOpciones, Producto

    grupos = list(GrupoOpciones.objects.filter(diario=True, activo=True).prefetch_related("opciones"))
    hoy = date_format(timezone.localdate(), "l j \\d\\e F")
    lineas = [f"*Menú de hoy* · {hoy}" + (f"\n{nombre_negocio}" if nombre_negocio else "")]
    for g in grupos:
        ops = [o for o in g.opciones.all() if o.activa and not o.agotada]
        if ops:
            plural = g.nombre if g.nombre.endswith("s") else g.nombre + ("es" if g.nombre[-1] not in "aeiou" else "s")
            lineas.append("\n*" + plural + "*\n" + "\n".join(f"• {o.nombre}" + (f" (+S/ {o.precio:.2f})" if o.precio else "") for o in ops))
    productos = Producto.objects.filter(activo=True, grupos__in=grupos).distinct().prefetch_related("variantes")
    precios = [f"{p.nombre}: S/ {p.precio:.2f}" for p in productos]
    if precios:
        lineas.append("\n" + "\n".join(precios))
    return "\n".join(lineas)
