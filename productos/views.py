from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, ProtectedError, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import entero, inicio_dia

from . import excel
from .forms import CategoriaForm, GenerarVariantesForm, GrupoOpcionesForm, ImportarForm, MovimientoForm, ProductoForm, VarianteForm
from .models import area_sugerida, CERO, Categoria, GrupoOpciones, MovimientoStock, Opcion, Producto, Variante
from .rubros import CATEGORIAS, GRUPOS, etiquetas_variantes, rubro_actual, valores_iniciales
from .servicios import ajustar_a, asegurar_variante_unica, generar_variantes, leer_linea_opcion, mover_stock, por_reponer

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel(contenido, nombre):
    resp = HttpResponse(contenido, content_type=XLSX)
    resp["Content-Disposition"] = content_disposition_header(True, f"{nombre}_{timezone.localdate():%Y%m%d}.xlsx")
    return resp


def _form(request, form, titulo, cancelar, breadcrumb, **extra):
    return render(request, "core/form.html", {"form": form, "titulo": titulo, "cancelar": cancelar,
                                              "breadcrumb": breadcrumb, **extra})


# --- Lista ---------------------------------------------------------------------

def _filtrar(request):
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("cat", "")
    estado = request.GET.get("estado", "activos")
    tipo = request.GET.get("tipo", "")
    productos = Producto.objects.select_related("categoria").prefetch_related(
        Prefetch("variantes", queryset=Variante.objects.filter(activa=True), to_attr="vars"))
    for palabra in q.split():
        productos = productos.filter(Q(nombre__icontains=palabra) | Q(variantes__codigo__iexact=palabra)
                                     | Q(variantes__nombre__icontains=palabra) | Q(categoria__nombre__icontains=palabra))
    if cat == "sin":
        productos = productos.filter(categoria__isnull=True)
    elif entero(cat):
        productos = productos.filter(categoria_id=entero(cat))
    if tipo in ("P", "S", "C"):
        productos = productos.filter(tipo=tipo)
    if estado == "inactivos":
        productos = productos.filter(activo=False)
    elif estado == "reponer":
        productos = productos.filter(pk__in=por_reponer().values("producto_id"))
    elif estado != "todos":
        productos = productos.filter(activo=True)
    filtros = {"q": q, "cat": cat, "estado": estado, "tipo": tipo}
    return productos.distinct().order_by("nombre"), filtros


def _resumir(productos):
    for p in productos:
        nombradas = [v for v in p.vars if v.nombre]
        p.n_variantes = len(nombradas)
        p.stock_suma = sum((v.stock for v in p.vars), CERO)
        p.reponer = p.maneja_stock and any(v.stock <= p.stock_minimo for v in p.vars)
        precios = {v.precio_venta for v in p.vars} or {p.precio}
        p.precio_min, p.precio_max = min(precios), max(precios)
        p.codigo = p.vars[0].codigo if len(p.vars) == 1 else ""
    return productos


@permiso_requerido("productos.ver")
def lista(request):
    productos, filtros = _filtrar(request)
    pagina = Paginator(productos, 30).get_page(request.GET.get("page"))
    _resumir(pagina.object_list)
    query = request.GET.copy()
    query.pop("page", None)
    contexto = {"pagina": pagina, "f": filtros, "query": query, "total": pagina.paginator.count,
                "hay_productos": Producto.objects.exists()}
    if request.htmx and not request.htmx.boosted:
        return render(request, "productos/partials/tabla.html", contexto)
    contexto["categorias"] = Categoria.objects.all()
    contexto["n_reponer"] = por_reponer().values("producto_id").distinct().count()
    return render(request, "productos/lista.html", contexto)


@permiso_requerido("productos.ver")
def exportar(request):
    productos, _ = _filtrar(request)
    variantes = (Variante.objects.filter(producto__in=productos, activa=True)
                 .select_related("producto__categoria").order_by("producto__nombre", "orden", "id"))
    return _excel(excel.exportar(variantes, puede(request.user, "productos.costos")), "productos")


# --- Crear / editar ----------------------------------------------------------------

@permiso_requerido("productos.editar")
def producto_form(request, pk=None):
    producto = get_object_or_404(Producto, pk=pk) if pk else None
    inicial = {} if producto else valores_iniciales()
    if not producto and entero(request.GET.get("cat")):
        inicial["categoria"] = entero(request.GET.get("cat"))
    imagen_antes = producto.imagen.name if producto and producto.imagen else ""
    form = ProductoForm(request.POST or None, request.FILES or None, instance=producto, initial=inicial)
    if not puede(request.user, "productos.costos"):
        del form.fields["costo"]
    if request.method == "POST" and form.is_valid():
        from core.bitacora import anotar, cambios_form

        cambio = cambios_form(form, ["precio", "costo"]) if producto else {}
        with transaction.atomic():
            p = form.save()
            for campo, (antes, despues) in cambio.items():
                anotar(f"producto.{campo}", f"{p.nombre}: {campo} S/ {antes if antes is not None else '—'} → S/ {despues if despues is not None else '—'}",
                       objeto=p, antes={campo: antes}, despues={campo: despues})
            if not form.con_variantes:
                v = asegurar_variante_unica(p)
                if "codigo" in form.cleaned_data and v.codigo != form.cleaned_data["codigo"]:
                    v.codigo = form.cleaned_data["codigo"]
                    v.save(update_fields=["codigo"])
                stock = form.cleaned_data.get("stock_inicial")
                if stock:
                    mover_stock(v, stock, MovimientoStock.Tipo.INICIAL, request.user, "Al crear el producto",
                                costo_unitario=p.costo)
        if p.imagen and p.imagen.name != imagen_antes:
            try:
                p.procesar_imagen()
            except Exception:
                p.imagen = imagen_antes or None
                p.save(update_fields=["imagen"])
                messages.warning(request, "No se pudo procesar la imagen; prueba con otra foto (JPG o PNG).")
        messages.success(request, f"«{p.nombre}» guardado.")
        if "otro" in request.POST:
            url = reverse("productos:nuevo")
            return redirect(f"{url}?cat={p.categoria_id}" if p.categoria_id else url)
        return redirect("productos:detalle", pk=p.pk)
    return render(request, "productos/form.html", {"form": form, "producto": producto})


@permiso_requerido("productos.editar")
@require_POST
def producto_eliminar(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    usado = MovimientoStock.objects.filter(variante__producto=producto).exclude(tipo=MovimientoStock.Tipo.INICIAL).exists()
    if usado:
        messages.error(request, f"«{producto.nombre}» ya tiene movimientos de stock o ventas. Desactívalo en vez de borrarlo.")
        return redirect("productos:detalle", pk=pk)
    try:
        with transaction.atomic():
            from core.bitacora import anotar

            anotar("producto.eliminado", f"Producto «{producto.nombre}» eliminado (no tenía ventas ni movimientos)", objeto=producto,
                   despues={"precio": producto.precio, "costo": producto.costo})
            MovimientoStock.objects.filter(variante__producto=producto).delete()
            producto.delete()
    except ProtectedError:
        messages.error(request, f"«{producto.nombre}» ya se vendió. Desactívalo en vez de borrarlo.")
        return redirect("productos:detalle", pk=pk)
    messages.success(request, f"«{producto.nombre}» eliminado.")
    return redirect("productos:lista")


# --- Detalle y variantes ------------------------------------------------------------

@permiso_requerido("productos.ver")
def detalle(request, pk):
    producto = get_object_or_404(Producto.objects.select_related("categoria"), pk=pk)
    variantes = list(producto.variantes.filter(activa=True).annotate(n_mov=Count("movimientos")))
    movimientos = (MovimientoStock.objects.filter(variante__producto=producto)
                   .select_related("variante", "usuario")[:15])
    e1, _, e2, _ = etiquetas_variantes()
    ultima = None
    if producto.maneja_stock and puede(request.user, "compras.ver"):  # solo con el módulo Compras
        from compras.servicios import ultima_de_producto

        ultima = ultima_de_producto(producto)
    from core.permisos import acceso_total

    historial = []
    if acceso_total(request.user):
        from core.bitacora import de_objetos

        historial = de_objetos([producto, *producto.variantes.all()])
    return render(request, "productos/detalle.html", {
        "ultima_compra": ultima, "historial": historial, "historial_tipo": "producto", "historial_id": producto.pk,
        "p": producto,
        "variantes": variantes,
        "con_variantes": any(v.nombre for v in variantes),
        "movimientos": movimientos,
        "form_generar": GenerarVariantesForm(),
        "etiqueta_variantes": f"{e1} y {e2.lower()}" if e2 else e1,
        "ver_costos": puede(request.user, "productos.costos"),
        **_datos_componentes(producto),
        **(_datos_combo(producto) if producto.es_combo else {}),
    })


def _datos_componentes(producto):
    return {"componentes": list(producto.componentes.select_related("cambiar_con")),
            "grupos_cambio": GrupoOpciones.objects.filter(activo=True, diario=False, maximo=1).order_by("orden", "nombre")}


def _datos_combo(combo):
    """Lo que trae el combo, las partes a elegir y cuánto costaría todo por separado."""
    items = list(combo.combo_items.select_related("variante__producto"))
    partes = [g for g in combo.grupos.filter(activo=True).prefetch_related("opciones__variante__producto")
              if any(o.variante_id for o in g.opciones.all())]
    separado = sum((i.variante.precio_venta * i.cantidad for i in items), CERO)
    for g in partes:
        precios = [o.variante.precio_venta for o in g.opciones.all() if o.activa and o.variante_id]
        if precios:
            separado += min(precios)
    elegibles = (Variante.objects.filter(activa=True, producto__activo=True).exclude(producto__tipo=Producto.Tipo.COMBO)
                 .select_related("producto__categoria").order_by("producto__categoria__orden", "producto__categoria__nombre", "producto__nombre", "orden"))
    return {"combo_items": items, "combo_partes": partes, "combo_separado": separado,
            "combo_ahorro": separado - combo.precio if separado > combo.precio else None, "combo_elegibles": elegibles}


@permiso_requerido("productos.editar")
@require_POST
def combo(request, pk):
    """Arma el combo: agregar o quitar productos fijos, y partes a elegir (gaseosa: Inca o Coca)."""
    from .models import ComboItem, Opcion

    p = get_object_or_404(Producto, pk=pk, tipo=Producto.Tipo.COMBO)
    accion = request.POST.get("accion")
    error = ""
    try:
        if accion == "agregar":
            v = get_object_or_404(Variante.objects.select_related("producto"), pk=entero(request.POST.get("variante")))
            if v.producto.es_combo:
                raise ValueError("Un combo no puede traer otro combo.")
            cantidad = Decimal(str(request.POST.get("cantidad") or "1").replace(",", "."))
            if not cantidad.is_finite() or cantidad <= 0 or cantidad > 99:
                raise ValueError("Cantidad no válida.")
            item = p.combo_items.filter(variante=v).first()
            if item:
                item.cantidad += cantidad
                item.save(update_fields=["cantidad"])
            else:
                orden = (p.combo_items.order_by("-orden").values_list("orden", flat=True).first() or 0) + 1
                ComboItem.objects.create(combo=p, variante=v, cantidad=cantidad, orden=orden)
        elif accion in ("mas", "menos", "quitar"):
            item = get_object_or_404(ComboItem, pk=entero(request.POST.get("item")), combo=p)
            if accion == "quitar" or (accion == "menos" and item.cantidad <= 1):
                item.delete()
            else:
                item.cantidad += 1 if accion == "mas" else -1
                item.save(update_fields=["cantidad"])
        elif accion == "parte":
            nombre = " ".join(request.POST.get("nombre", "").split())[:40]
            vs = list(Variante.objects.filter(pk__in=[entero(x) for x in request.POST.getlist("variantes") if entero(x)])
                      .exclude(producto__tipo=Producto.Tipo.COMBO).select_related("producto"))
            if not nombre or len(vs) < 2:
                raise ValueError("Escribe el nombre de la parte (ej.: Gaseosa) y marca al menos dos productos para elegir.")
            base = f"{p.nombre}: {nombre}"[:60]
            titulo, n = base, 2
            while GrupoOpciones.objects.filter(nombre=titulo).exists():
                titulo, n = f"{base[:56]} ({n})", n + 1
            g = GrupoOpciones.objects.create(nombre=titulo, minimo=1, maximo=1, orden=0)
            for i, v in enumerate(vs):
                Opcion.objects.create(grupo=g, nombre=v.nombre_completo[:60], variante=v, orden=i, por_defecto=i == 0)
            p.grupos.add(g)
        elif accion == "quitar_parte":
            g = get_object_or_404(GrupoOpciones, pk=entero(request.POST.get("grupo")))
            p.grupos.remove(g)
            if not g.productos.exists():
                g.delete()
    except (ValueError, ArithmeticError) as e:
        error = str(e) if str(e) else "Dato no válido."
        if not request.htmx:
            messages.error(request, error)
    if request.htmx:
        return render(request, "productos/partials/combo.html", {"p": p, "error": error, **_datos_combo(p)})
    return redirect("productos:detalle", pk=pk)


@permiso_requerido("productos.editar")
@require_POST
def componentes(request, pk):
    """Qué lleva el plato: agregar, quitar, ordenar y decir si se puede quitar o cambiar."""
    from .models import Componente

    p = get_object_or_404(Producto, pk=pk)
    accion = request.POST.get("accion")
    if accion == "agregar":
        nombres = [" ".join(n.split())[:60] for n in request.POST.get("nombre", "").replace(",", "\n").splitlines()]
        grupo = GrupoOpciones.objects.filter(pk=entero(request.POST.get("cambiar_con")), activo=True).first()
        orden = (p.componentes.order_by("-orden").values_list("orden", flat=True).first() or 0) + 1
        for i, nombre in enumerate(n for n in nombres if n):
            if p.componentes.filter(nombre__iexact=nombre).exists():
                continue
            Componente.objects.create(producto=p, nombre=nombre, orden=orden + i, quitable=request.POST.get("quitable") == "1",
                                      cambiar_con=grupo if i == 0 else None)
            if grupo and i == 0:
                p.grupos.add(grupo)  # para cambiar algo, el grupo tiene que estar en el plato
    else:
        c = get_object_or_404(Componente, pk=entero(request.POST.get("componente")), producto=p)
        if accion == "borrar":
            c.delete()
        elif accion == "quitable":
            c.quitable = not c.quitable
            c.save(update_fields=["quitable"])
        elif accion == "cambiar":
            c.cambiar_con = GrupoOpciones.objects.filter(pk=entero(request.POST.get("cambiar_con")), activo=True).first()
            c.save(update_fields=["cambiar_con"])
            if c.cambiar_con:
                p.grupos.add(c.cambiar_con)
        elif accion in ("subir", "bajar"):
            lista = list(p.componentes.all())
            i = lista.index(c)
            j = i - 1 if accion == "subir" else i + 1
            if 0 <= j < len(lista):
                lista[i], lista[j] = lista[j], lista[i]
                for n, x in enumerate(lista):
                    if x.orden != n:
                        x.orden = n
                        x.save(update_fields=["orden"])
    if request.htmx:
        return render(request, "productos/partials/componentes.html", {"p": p, **_datos_componentes(p)})
    return redirect("productos:detalle", pk=pk)


@permiso_requerido("productos.editar")
@require_POST
def variantes_generar(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    form = GenerarVariantesForm(request.POST)
    if form.is_valid():
        try:
            creadas, existian = generar_variantes(producto, form.cleaned_data["opciones1"], form.cleaned_data["opciones2"])
        except ValueError as e:
            messages.error(request, str(e))
        else:
            msg = f"Se crearon {creadas} variante{'s' if creadas != 1 else ''}."
            if existian:
                msg += f" {existian} ya existían."
            messages.success(request, msg + " Ponles código o un precio distinto si hace falta.")
    else:
        messages.error(request, "Escribe al menos una opción.")
    return redirect(reverse("productos:detalle", args=[pk]) + "#variantes")


@permiso_requerido("productos.editar")
def variante_editar(request, pk):
    v = get_object_or_404(Variante.objects.select_related("producto"), pk=pk)
    form = VarianteForm(request.POST or None, instance=v, ver_costos=puede(request.user, "productos.costos"))
    if request.method == "POST" and form.is_valid():
        from core.bitacora import anotar, cambios_form

        with transaction.atomic():
            for campo, (antes, despues) in cambios_form(form, ["precio", "costo"]).items():
                anotar(f"producto.{campo}", f"{v.nombre_completo}: {campo} S/ {antes if antes is not None else '—'} → "
                       f"S/ {despues if despues is not None else '—'}", objeto=v, antes={campo: antes}, despues={campo: despues})
            form.save()
        messages.success(request, f"Variante «{v.nombre}» guardada.")
        return redirect(reverse("productos:detalle", args=[v.producto_id]) + "#variantes")
    url = reverse("productos:detalle", args=[v.producto_id])
    return _form(request, form, f"Variante {v.nombre}", url,
                 [("Productos", reverse("productos:lista")), (v.producto.nombre, url)],
                 subtitulo=v.producto.nombre, ayuda=f"Precio del producto: S/ {v.producto.precio}. Déjalo vacío para usar ese.")


@permiso_requerido("productos.editar")
@require_POST
def variante_eliminar(request, pk):
    v = get_object_or_404(Variante.objects.select_related("producto"), pk=pk)
    producto = v.producto
    if v.stock != CERO:
        messages.error(request, f"«{v.nombre}» todavía tiene stock ({v.stock.normalize():f}). Ajústalo a 0 primero.")
    elif v.movimientos.exists() or _vendida(v):
        v.activa = False
        v.save(update_fields=["activa"])
        messages.success(request, f"«{v.nombre}» tiene historial: se desactivó en vez de borrarse.")
    else:
        v.delete()
        messages.success(request, f"Variante «{v.nombre}» eliminada.")
    if not producto.variantes.filter(activa=True).exists():
        asegurar_variante_unica(producto)
        messages.info(request, "El producto quedó sin variantes: ahora se vende y se cuenta como uno solo.")
    return redirect(reverse("productos:detalle", args=[producto.pk]) + "#variantes")


def _vendida(variante):
    """¿Ya se vendió, se movió o está pedida en alguna mesa? Entonces no se borra: se desactiva."""
    from .servicios import en_uso

    return en_uso(variante)


# --- Stock ---------------------------------------------------------------------------

@permiso_requerido("productos.stock")
def movimiento(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    if not producto.maneja_stock:
        messages.info(request, f"«{producto.nombre}» no controla stock. Actívalo en Editar si lo necesitas.")
        return redirect("productos:detalle", pk=pk)
    ver_costos = puede(request.user, "productos.costos")
    inicial = {"operacion": request.GET.get("op", "ING")}
    if entero(request.GET.get("variante")):
        inicial["variante"] = entero(request.GET.get("variante"))
    form = MovimientoForm(request.POST or None, producto=producto, ver_costos=ver_costos, initial=inicial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        v, op = d["variante"], d["operacion"]
        if op == "AJU":
            mov = ajustar_a(v, d["cantidad"], request.user, d["nota"] or "Conteo de inventario")
        else:
            cantidad = d["cantidad"] if op == "ING" else -d["cantidad"]
            mov = mover_stock(v, cantidad, op, request.user, d["nota"], d.get("costo_unitario") if op == "ING" else None,
                              d["referencia"])
        if mov is None:
            messages.info(request, "El stock ya era ese; no se registró nada.")
        else:
            messages.success(request, f"{mov.get_tipo_display()} registrado. Stock de {v.nombre or producto.nombre}: {v.stock.normalize():f}.")
        if "otro" in request.POST:
            return redirect(reverse("productos:movimiento", args=[pk]) + f"?op={op}")
        return redirect("productos:detalle", pk=pk)
    return render(request, "productos/movimiento.html", {"form": form, "p": producto})


@permiso_requerido("productos.stock")
def kardex(request):
    movs = MovimientoStock.objects.select_related("variante__producto", "usuario")
    q = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "")
    desde, hasta = request.GET.get("desde", ""), request.GET.get("hasta", "")
    for palabra in q.split():
        movs = movs.filter(Q(variante__producto__nombre__icontains=palabra) | Q(variante__nombre__icontains=palabra)
                           | Q(variante__codigo__iexact=palabra) | Q(referencia__icontains=palabra))
    if tipo in MovimientoStock.Tipo.values:
        movs = movs.filter(tipo=tipo)
    try:
        if desde:
            movs = movs.filter(fecha__gte=inicio_dia(desde))
        if hasta:
            movs = movs.filter(fecha__lt=inicio_dia(hasta + timedelta(days=1)))
    except Exception:
        desde = hasta = ""
    if request.GET.get("excel"):
        return _excel(_kardex_excel(movs[:20000]), "movimientos_stock")
    pagina = Paginator(movs, 40).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "productos/kardex.html", {
        "pagina": pagina, "query": query, "tipos": MovimientoStock.Tipo.choices,
        "f": {"q": q, "tipo": tipo, "desde": desde, "hasta": hasta},
    })


def _kardex_excel(movs):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core.excel import a_bytes

    wb = Workbook()
    ws = wb.active
    ws.title = "Movimientos"
    ws.append(["Fecha", "Producto", "Variante", "Código", "Movimiento", "Cantidad", "Saldo", "Costo unit.", "Referencia", "Nota", "Usuario"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for m in movs:
        ws.append([timezone.localtime(m.fecha).strftime("%d/%m/%Y %H:%M"), m.variante.producto.nombre, m.variante.nombre,
                   m.variante.codigo, m.get_tipo_display(), float(m.cantidad), float(m.saldo),
                   float(m.costo_unitario) if m.costo_unitario is not None else None, m.referencia, m.nota,
                   (m.usuario.get_full_name() or m.usuario.username) if m.usuario else ""])
    return a_bytes(wb)


# --- Categorías ------------------------------------------------------------------------

@permiso_requerido("productos.editar")
def categorias(request):
    form = CategoriaForm(request.POST or None, initial={"orden": (Categoria.objects.count() + 1) * 10})
    if request.method == "POST" and form.is_valid():
        c = form.save()
        messages.success(request, f"Categoría «{c.nombre}» creada.")
        return redirect("productos:categorias")
    lista = Categoria.objects.annotate(n=Count("productos", filter=Q(productos__activo=True)))
    rubro = rubro_actual()
    sugeridas = [n for n in CATEGORIAS.get(rubro, []) if not Categoria.objects.filter(nombre__iexact=n).exists()]
    return render(request, "productos/categorias.html", {"form": form, "categorias": lista, "sugeridas": sugeridas})


@permiso_requerido("productos.editar")
@require_POST
def categorias_sugeridas(request):
    nombres = [n for n in request.POST.getlist("nombre") if n in CATEGORIAS.get(rubro_actual(), [])]
    orden = (Categoria.objects.count() + 1) * 10
    creadas = 0
    for n in nombres:
        _, nueva = Categoria.objects.get_or_create(nombre=n, defaults={"orden": orden, "area": area_sugerida(n)})
        orden += 10
        creadas += nueva
    messages.success(request, f"Se crearon {creadas} categorías.")
    return redirect("productos:categorias")


@permiso_requerido("productos.editar")
def categoria_editar(request, pk):
    c = get_object_or_404(Categoria, pk=pk)
    form = CategoriaForm(request.POST or None, instance=c)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoría guardada.")
        return redirect("productos:categorias")
    return _form(request, form, f"Categoría {c.nombre}", reverse("productos:categorias"),
                 [("Productos", reverse("productos:lista")), ("Categorías", reverse("productos:categorias"))])


@permiso_requerido("productos.editar")
@require_POST
def categoria_eliminar(request, pk):
    c = get_object_or_404(Categoria, pk=pk)
    n = c.productos.count()
    c.delete()
    messages.success(request, f"Categoría «{c.nombre}» eliminada." + (f" {n} producto(s) quedaron sin categoría." if n else ""))
    return redirect("productos:categorias")


# --- Importar ---------------------------------------------------------------------------

SESION_IMPORTAR = "productos_importar"


@permiso_requerido("productos.editar")
def plantilla(request):
    return _excel(excel.plantilla(), "plantilla_productos")


@permiso_requerido("productos.editar")
def importar(request):
    if request.method == "POST" and "confirmar" in request.POST:
        filas = request.session.pop(SESION_IMPORTAR, None)
        if not filas:
            messages.error(request, "La revisión expiró. Vuelve a subir el archivo.")
            return redirect("productos:importar")
        if not puede(request.user, "productos.stock"):
            for f in filas:
                f["stock"] = None
        try:
            creados, actualizados = excel.importar(filas, request.user)
        except ValueError as e:
            messages.error(request, f"No se importó nada: {e}")
            return redirect("productos:importar")
        from core.bitacora import anotar

        anotar("productos.importados", f"Importación de Excel: {creados} productos nuevos y {actualizados} actualizados",
               despues={"nuevos": creados, "actualizados": actualizados})
        messages.success(request, f"Importación lista: {creados} nuevos y {actualizados} actualizados.")
        return redirect("productos:lista")

    form = ImportarForm(request.POST or None, request.FILES or None)
    contexto = {"form": form}
    if request.method == "POST" and form.is_valid():
        filas, errores = excel.leer(form.cleaned_data["archivo"])
        con_error = [f for f in filas if f["errores"]]
        contexto.update({"filas": filas, "errores": errores, "con_error": con_error})
        if filas and not errores and not con_error:
            request.session[SESION_IMPORTAR] = filas
            contexto.update({"listo": True, "nuevos": sum(f["accion"] == "nuevo" for f in filas),
                             "actualizar": sum(f["accion"] == "actualizar" for f in filas),
                             "sin_permiso_stock": not puede(request.user, "productos.stock")})
    return render(request, "productos/importar.html", contexto)


# --- Opciones al pedir ------------------------------------------------------------------

@permiso_requerido("productos.editar")
def opciones(request):
    grupos = GrupoOpciones.objects.prefetch_related(
        Prefetch("opciones", queryset=Opcion.objects.filter(activa=True)), Prefetch("productos", queryset=Producto.objects.order_by("nombre")))
    existentes = {g.nombre.lower() for g in grupos}
    sugeridos = [g for g in GRUPOS.get(rubro_actual(), []) if g[0].lower() not in existentes]
    return render(request, "productos/opciones.html", {"grupos": grupos, "sugeridos": sugeridos})


@permiso_requerido("productos.editar")
def grupo_form(request, pk=None):
    grupo = get_object_or_404(GrupoOpciones, pk=pk) if pk else None
    form = GrupoOpcionesForm(request.POST or None, instance=grupo,
                             initial={} if grupo else {"orden": (GrupoOpciones.objects.count() + 1) * 10})
    if request.method == "POST" and form.is_valid():
        g = form.save()
        messages.success(request, f"«{g.nombre}» guardado: {g.opciones.filter(activa=True).count()} opciones, usado en {g.productos.count()} productos.")
        return redirect("productos:opciones")
    return render(request, "productos/grupo_form.html", {"form": form, "grupo": grupo})


@permiso_requerido("productos.editar")
@require_POST
def grupo_eliminar(request, pk):
    g = get_object_or_404(GrupoOpciones, pk=pk)
    g.delete()  # los pedidos y ventas guardan su propia copia de las opciones elegidas
    messages.success(request, f"Grupo «{g.nombre}» eliminado.")
    return redirect("productos:opciones")


@permiso_requerido("productos.editar")
@require_POST
def grupos_sugeridos(request):
    from django.db import transaction

    elegidos = set(request.POST.getlist("nombre"))
    creados = 0
    with transaction.atomic():
        for nombre, mn, mx, ops in GRUPOS.get(rubro_actual(), []):
            if nombre not in elegidos or GrupoOpciones.objects.filter(nombre__iexact=nombre).exists():
                continue
            g = GrupoOpciones.objects.create(nombre=nombre, minimo=mn, maximo=mx, orden=(GrupoOpciones.objects.count() + 1) * 10)
            for i, linea in enumerate(ops):
                n, p, defecto = leer_linea_opcion(linea)
                Opcion.objects.create(grupo=g, nombre=n, precio=p, orden=i, por_defecto=defecto)
            creados += 1
    messages.success(request, f"Se crearon {creados} grupos. Ahora elige en qué productos se usa cada uno (botón Editar).")
    return redirect("productos:opciones")


# --- Agotados de hoy ------------------------------------------------------------------

@permiso_requerido("productos.agotar")
def agotados(request):
    from .servicios import marcar_agotado

    if request.method == "POST":
        objeto = None
        if request.POST.get("producto"):
            objeto = get_object_or_404(Producto, pk=entero(request.POST.get("producto")))
        elif request.POST.get("opcion"):
            objeto = get_object_or_404(Opcion, pk=entero(request.POST.get("opcion")))
        if objeto is not None:
            marcar_agotado(objeto, request.POST.get("agotado") == "1")
        if not request.htmx:
            return redirect(request.get_full_path())
    q = request.GET.get("q", "").strip()
    productos = Producto.objects.filter(activo=True).select_related("categoria").order_by("categoria__orden", "categoria__nombre", "nombre")
    if q:
        productos = productos.filter(nombre__icontains=q)
    opciones_ = Opcion.objects.filter(activa=True, grupo__activo=True).select_related("grupo").order_by("grupo__orden", "orden")
    if q:
        opciones_ = opciones_.filter(nombre__icontains=q)
    contexto = {"productos": productos, "opciones": opciones_, "q": q,
                "n_agotados": sum(1 for p in productos if p.agotado) + sum(1 for o in opciones_ if o.agotada)}
    if request.htmx:
        return render(request, "productos/partials/agotados.html", contexto)
    return render(request, "productos/agotados.html", contexto)


# --- Menú del día ------------------------------------------------------------------

def _datos_menu():
    from .servicios import menu_texto
    from core.models import Ajustes

    grupos = list(GrupoOpciones.objects.filter(diario=True).order_by("orden", "nombre").prefetch_related("opciones", "productos"))
    for g in grupos:
        ops = list(g.opciones.all())
        g.hoy = [o for o in ops if o.activa]
        g.otros = sorted([o for o in ops if not o.activa], key=lambda o: o.nombre.lower())
    productos = Producto.objects.filter(activo=True, grupos__diario=True).distinct().order_by("nombre")
    return {"grupos": grupos, "productos_menu": productos, "texto": menu_texto(Ajustes.cargar().nombre or "") if grupos else ""}


@permiso_requerido("productos.menu")
def menu_dia(request):
    from .servicios import menu_agregar, menu_crear, menu_limpiar

    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "crear":
                menu_crear()
            elif accion == "agregar":
                g = get_object_or_404(GrupoOpciones, pk=entero(request.POST.get("grupo")), diario=True)
                menu_agregar(g, request.POST.get("nombre"), request.POST.get("precio"))
            elif accion in ("poner", "sacar", "agotar"):
                o = get_object_or_404(Opcion, pk=entero(request.POST.get("opcion")), grupo__diario=True)
                if accion == "poner":
                    menu_agregar(o.grupo, o.nombre)
                elif accion == "sacar":
                    o.activa, o.agotada_en = False, None
                    o.save(update_fields=["activa", "agotada_en"])
                else:
                    from .servicios import marcar_agotado

                    marcar_agotado(o, not o.agotada)
            elif accion == "limpiar":
                n = menu_limpiar()
                messages.info(request, f"Menú vacío ({n} platos guardados para otro día). Elige los de hoy.")
        except ValueError as e:
            messages.error(request, str(e))
        if not request.htmx:
            return redirect("productos:menu")
    datos = _datos_menu()
    if request.htmx:
        return render(request, "productos/partials/menu.html", datos)
    return render(request, "productos/menu.html", datos)
