import json
from decimal import Decimal
from urllib.parse import quote

from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import entero

from .models import Cuenta, ItemCuenta, Mesa, Zona
from core.autorizacion import AutorizacionError, autorizar

from .servicios import (MesaError, abrir_cuenta, abrir_delivery, agregar, anular_cuenta, cambiar_cantidad, cobrar, cortesia, datos_delivery,
                        entregar_delivery, enviar_cocina, falta_de_cocina, juntar, cambiar_personas, cuenta_de_mesa, unir_mesas, separar_mesa, liberar_mesa, marcar_listo, marcar_servido, mover,
                        poner_envio, quitar, salio_delivery)


def _abiertas():
    return Cuenta.objects.filter(estado=Cuenta.Estado.ABIERTA).select_related("mesa", "mozo").prefetch_related(
        "mesas_unidas", Prefetch("items", queryset=ItemCuenta.objects.filter(anulado=False), to_attr="vigentes"))


def _datos_mapa():
    abiertas = list(_abiertas())
    cuentas = {c.mesa_id: c for c in abiertas if c.mesa_id}
    pegadas = {m.pk: c for c in abiertas if c.mesa_id for m in c.unidas}
    zonas = []
    for z in Zona.objects.prefetch_related(Prefetch("mesas", queryset=Mesa.objects.filter(activa=True))):
        mesas = list(z.mesas.all())
        for m in mesas:
            m.cuenta = cuentas.get(m.pk)
            m.pegada = pegadas.get(m.pk) if not m.cuenta else None
            if m.cuenta:
                m.cuenta.total = sum((i.subtotal for i in m.cuenta.vigentes), 0)
                m.cuenta.sin_enviar = sum(1 for i in m.cuenta.vigentes if not i.enviado_en)
                m.cuenta.listos = sum(1 for i in m.cuenta.vigentes if i.listo_en and not i.servido_en)
                m.cuenta.esta_pagada = m.cuenta.pagada(m.cuenta.vigentes)
        if mesas:
            zonas.append({"zona": z, "mesas": mesas, "libres": sum(1 for m in mesas if not m.cuenta and not m.pegada)})
    sin_mesa = [c for c in abiertas if not c.mesa_id]
    for c in sin_mesa:
        c.total = sum((i.subtotal for i in c.vigentes), 0)
        c.sin_enviar = sum(1 for i in c.vigentes if not i.enviado_en)
        c.listos = sum(1 for i in c.vigentes if i.listo_en and not i.servido_en)
        c.esta_pagada = c.pagada(c.vigentes)
    llevar = [c for c in sin_mesa if not c.es_delivery]
    delivery = sorted([c for c in sin_mesa if c.es_delivery], key=lambda c: (c.estado_envio == Cuenta.Envio.EN_CAMINO, c.abierta_en))
    return {"zonas": zonas, "llevar": llevar, "delivery": delivery, "ahora": timezone.now()}


@permiso_requerido("mesas.atender", "mesas.cobrar")
def mapa(request):
    datos = _datos_mapa()
    if request.htmx:
        return render(request, "mesas/partials/mapa.html", datos)
    datos["hay_mesas"] = Mesa.objects.exists()
    return render(request, "mesas/mapa.html", datos)


@permiso_requerido("mesas.atender")
@require_POST
def abrir(request):
    mesa = get_object_or_404(Mesa, pk=entero(request.POST.get("mesa"))) if request.POST.get("mesa") else None
    try:
        cuenta = abrir_cuenta(request.user, mesa, entero(request.POST.get("personas")) or 0, request.POST.get("nombre", ""))
    except MesaError as e:
        messages.error(request, str(e))
        ocupada = cuenta_de_mesa(mesa)
        return redirect("mesas:cuenta", pk=ocupada.pk) if ocupada else redirect("mesas:mapa")
    if mesa and request.POST.get("juntar"):
        return redirect(reverse("mesas:cambiar", args=[cuenta.pk]) + "?nueva=1")
    return redirect(reverse("mesas:agregar", args=[cuenta.pk]))


def _por_area(items):
    """Lo recién enviado, separado: [(código, nombre, items)] en orden cocina, barra, mozo."""
    nombres = {"COC": "Cocina", "BAR": "Barra", "MOZ": "Llévalo tú"}
    return [(a, nombres[a], [i for i in items if i.area == a]) for a in ("COC", "BAR", "MOZ") if any(i.area == a for i in items)]


def _cuenta(pk):
    return get_object_or_404(Cuenta.objects.select_related("mesa__zona", "mozo").prefetch_related("mesas_unidas"), pk=pk)


@permiso_requerido("mesas.atender", "mesas.cobrar")
def cuenta(request, pk):
    c = _cuenta(pk)
    items = list(c.items.select_related("agregado_por", "venta").order_by("creado", "id"))
    por_enviar = [i for i in items if not i.anulado and not i.enviado_en and not i.venta_id]
    enviados = [i for i in items if not i.anulado and i.enviado_en and not i.venta_id]
    pagados = [i for i in items if i.venta_id and not i.anulado]
    anulados = [i for i in items if i.anulado]
    recien = parse_datetime(request.GET.get("enviado", "") or "")
    from caja.servicios import CajaError, sesion_para_vender

    try:
        sesion_para_vender(request.user)
        falta_caja = False
    except CajaError:
        falta_caja = True
    return render(request, "mesas/cuenta.html", {
        "c": c, "por_enviar": por_enviar, "enviados": enviados, "pagados": pagados, "anulados": anulados,
        "pendiente": sum((i.subtotal for i in por_enviar + enviados), 0),
        "ventas": sorted({i.venta for i in pagados}, key=lambda v: v.numero),
        "recien": [i for i in items if recien and not i.anulado and not i.es_envio and i.enviado_en == recien],
        "recien_areas": _por_area([i for i in items if recien and not i.anulado and not i.es_envio and i.enviado_en == recien]),
        "esta_pagada": c.pagada(items),
        # al cobrar todo: ¿se libera la mesa? Por defecto sí, salvo que algo no haya salido de cocina (o el delivery no se entregó)
        "liberar_al_cobrar": (c.estado_envio == Cuenta.Envio.ENTREGADO) if c.es_delivery else not falta_de_cocina(por_enviar + enviados + pagados),
        "repartidores": list(Cuenta.objects.exclude(repartidor="").order_by("-salio_en").values_list("repartidor", flat=True).distinct()[:30])
        if c.es_delivery else [],
        "recien_ts": request.GET.get("enviado", ""),
        "falta_caja": falta_caja and puede(request.user, "mesas.cobrar"),
        "puede_anular": puede(request.user, "mesas.anular"),
        "hay_listos": any(i.listo_en and not i.servido_en for i in enviados + pagados),
        "imprimir_precuenta": request.GET.get("precuenta") == "1",
        "motivos_cortesia": ["Plato salió mal", "Demora", "Cumpleaños", "Cliente frecuente", "Consumo del personal", "Invitación del dueño"],
    })


@permiso_requerido("mesas.atender")
def agregar_vista(request, pk):
    c = _cuenta(pk)
    if request.method == "POST":
        try:
            datos = json.loads(request.body or b"{}")
            agregar(c, datos.get("items") or [], request.user)
        except (ValueError, AttributeError):
            return JsonResponse({"error": "Datos no válidos."}, status=400)
        except MesaError as e:
            return JsonResponse({"error": str(e)}, status=400)
        if datos.get("enviar"):
            ts = enviar_cocina(c)
            url = reverse("mesas:cuenta", args=[c.pk]) + (f"?enviado={quote(ts.isoformat())}" if ts else "")
        else:
            url = reverse("mesas:cuenta", args=[c.pk])
        return JsonResponse({"ok": True, "url": url})
    if not c.abierta:
        return redirect("mesas:cuenta", pk=pk)
    from productos.models import Categoria
    from ventas.views import _catalogo

    categorias = Categoria.objects.filter(activa=True, productos__activo=True).distinct()
    return render(request, "mesas/agregar.html", {"c": c, "catalogo": _catalogo(),
                                                  "categorias": [{"id": x.pk, "n": x.nombre} for x in categorias]})


def _accion(request, pk, funcion, ok=None):
    c = _cuenta(pk)
    try:
        resultado = funcion(c)
        if ok:
            messages.success(request, ok)
        return c, resultado
    except MesaError as e:
        messages.error(request, str(e))
        return c, None


@permiso_requerido("mesas.atender")
@require_POST
def enviar(request, pk):
    c, ts = _accion(request, pk, enviar_cocina)
    if ts:
        return redirect(reverse("mesas:cuenta", args=[pk]) + f"?enviado={quote(ts.isoformat())}")
    if ts is None and c.abierta:
        messages.info(request, "No había nada nuevo para enviar.")
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender")
@require_POST
def item(request, pk):
    it = get_object_or_404(ItemCuenta.objects.select_related("cuenta"), pk=pk)
    accion = request.POST.get("accion")
    try:
        if accion in ("mas", "menos"):
            cambiar_cantidad(it, 1 if accion == "mas" else -1)
        elif accion == "quitar":
            quitar(it, request.user, request.POST.get("motivo"), puede(request.user, "mesas.anular"))
            messages.success(request, "Producto quitado.")
    except MesaError as e:
        messages.error(request, str(e))
    return redirect("mesas:cuenta", pk=it.cuenta_id)


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def cortesia_vista(request, pk):
    it = get_object_or_404(ItemCuenta.objects.select_related("cuenta"), pk=pk)
    from core.models import Ajustes

    if not Ajustes.cargar().cortesias_activas and request.POST.get("quitar") != "1":
        messages.error(request, "Las cortesías están desactivadas en Datos del negocio.")
        return redirect("mesas:cuenta", pk=it.cuenta_id)
    try:
        autoriza = autorizar(request, "mesas.cortesia", request.POST.get("sup_usuario"), request.POST.get("sup_clave"))
        quitar_ = request.POST.get("quitar") == "1"
        cortesia(it, autoriza, request.POST.get("motivo"), request.POST.get("cantidad"), quitar=quitar_)
        if quitar_:
            messages.info(request, f"{it.descripcion}: ya no es cortesía, se cobrará.")
        else:
            nombre = "" if autoriza == request.user else f" (autorizó {autoriza.get_full_name() or autoriza.username})"
            messages.success(request, f"{it.descripcion}: cortesía de la casa{nombre}.")
    except (AutorizacionError, MesaError) as e:
        messages.error(request, str(e))
    return redirect("mesas:cuenta", pk=it.cuenta_id)


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def personas(request, pk):
    try:
        cambiar_personas(_cuenta(pk), request.POST.get("personas"))
    except MesaError as e:
        messages.error(request, str(e))
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender")
@require_POST
def pedir_cuenta(request, pk):
    c = _cuenta(pk)
    if c.abierta:
        c.pidio_cuenta = not c.pidio_cuenta
        c.save(update_fields=["pidio_cuenta"])
    if c.pidio_cuenta:
        return redirect(reverse("mesas:cuenta", args=[pk]) + "?precuenta=1")
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender")
@require_POST
def servido(request, pk):
    c = _cuenta(pk)
    n = marcar_servido(c)
    if n:
        messages.success(request, f"Listo: {n} plato{'s' if n != 1 else ''} servido{'s' if n != 1 else ''}.")
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender", "mesas.cobrar")
def precuenta(request, pk):
    c = _cuenta(pk)
    total = c.total_por_cobrar
    return render(request, "mesas/precuenta.html", {"c": c, "items": c.por_cobrar().order_by("creado"), "total": total,
                                                    "propina_sugerida": (total / 10).quantize(total.__class__("0.10")),
                                                    "por_persona": (total / c.personas).quantize(total.__class__("0.01")) if c.personas > 1 and total and not c.es_delivery else None,
                                                    "pagado": sum((i.subtotal for i in c.items.filter(anulado=False, venta__isnull=False)), total.__class__("0"))})


@permiso_requerido("mesas.atender")
def comanda(request, pk):
    c = _cuenta(pk)
    ts = parse_datetime(request.GET.get("enviado", "") or "")
    area = _area(request)
    items = c.items.filter(anulado=False, enviado_en__isnull=False, es_envio=False, area=area)
    items = items.filter(enviado_en=ts) if ts else items
    return render(request, "mesas/comanda.html", {"c": c, "items": items, "ts": ts, "area": area})


@permiso_requerido("mesas.atender")
def cambiar_mesa(request, pk):
    """Mesas de la cuenta: juntar mesas libres, juntar con otra cuenta, separar o mudarse."""
    c = _cuenta(pk)
    if not c.mesa_id:
        return redirect("mesas:cuenta", pk=pk)
    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "unir":
                mesas = list(Mesa.objects.filter(pk__in=[entero(x) for x in request.POST.getlist("mesas") if entero(x)]))
                n = unir_mesas(c, mesas)
                c = _cuenta(pk)
                messages.success(request, f"Mesas juntas: {c.nombres_mesas}." if n else "Sin cambios.")
                return redirect("mesas:agregar" if request.POST.get("nueva") else "mesas:cuenta", pk=pk)
            if accion == "separar":
                separar_mesa(c, get_object_or_404(Mesa, pk=entero(request.POST.get("mesa"))))
                messages.success(request, "Mesa separada: quedó libre.")
                return redirect(reverse("mesas:cambiar", args=[pk]))
            destino = get_object_or_404(Mesa, pk=entero(request.POST.get("mesa")))
            if accion == "juntar_cuenta":
                otra = cuenta_de_mesa(destino)
                if not otra:
                    raise MesaError(f"La mesa {destino.nombre} ya no está ocupada.")
                juntar(c, otra)
                messages.success(request, f"Se juntó con {_cuenta(otra.pk).titulo}.")
                return redirect("mesas:cuenta", pk=otra.pk)
            mover(c, destino)
            messages.success(request, f"Se cambió a la mesa {destino.nombre}.")
            return redirect("mesas:cuenta", pk=pk)
        except MesaError as e:
            messages.error(request, str(e))
            return redirect(reverse("mesas:cambiar", args=[pk]))
    datos = _datos_mapa()
    modo = "mudar" if request.GET.get("modo") == "mudar" else "juntar"
    return render(request, "mesas/cambiar.html", {"c": c, "modo": modo, "nueva": request.GET.get("nueva"), **datos})


@permiso_requerido("mesas.cobrar")
@require_POST
def cobrar_vista(request, pk):
    c = _cuenta(pk)
    try:
        datos = json.loads(request.body or b"{}")
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Datos no válidos."}, status=400)
    descuento_por = None
    try:
        descuento = Decimal(str(datos.get("descuento") or 0))
    except Exception:  # noqa: BLE001
        return JsonResponse({"error": "Descuento no válido."}, status=400)
    if descuento > 0:
        if not str(datos.get("descuento_motivo") or "").strip():
            return JsonResponse({"error": "Indica el motivo del descuento."}, status=400)
        try:
            descuento_por = autorizar(request, "ventas.precio", datos.get("sup_usuario"), datos.get("sup_clave"))
        except AutorizacionError as e:
            return JsonResponse({"error": str(e)}, status=400)
    from django.db import transaction

    from facturacion.servicios import ComprobanteError, crear, enviar_seguro, preparar

    try:
        sol = preparar(datos)
        with transaction.atomic():  # si el comprobante no se puede armar, el cobro tampoco se guarda
            venta = cobrar(c, request.user, datos.get("pagos") or [], [entero(i) for i in datos.get("items") or [] if entero(i)],
                           datos.get("propina") or 0, datos.get("cliente_nombre", ""), datos.get("cliente_documento", ""),
                           _nota_cobro(c, datos), str(datos.get("token") or "")[:40] or None, cliente_id=entero(datos.get("cliente_id")),
                           puede_fiar=puede(request.user, "clientes.fiar"), puede_exceder_limite=puede(request.user, "clientes.limite"),
                           descuento=descuento, descuento_motivo=datos.get("descuento_motivo", ""), descuento_por=descuento_por,
                           liberar=datos.get("liberar", True) is not False)
            comprobante = crear(venta, sol, request.user)
    except (MesaError, ComprobanteError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    enviar_seguro(comprobante)
    c.refresh_from_db()
    if c.es_delivery and not c.abierta and c.estado_envio != Cuenta.Envio.ENTREGADO:  # se cobró y se cerró: ya se entregó
        Cuenta.objects.filter(pk=c.pk).update(estado_envio=Cuenta.Envio.ENTREGADO, entregado_en=timezone.now())
    if venta.enviado_cocina:  # se mandó a cocina al cobrar: al volver, la cuenta muestra qué dictar o la comanda
        siguiente = reverse("mesas:cuenta", args=[c.pk]) + "?enviado=" + quote(venta.enviado_cocina.isoformat())
    else:
        siguiente = reverse("mesas:mapa") if not c.abierta else reverse("mesas:cuenta", args=[c.pk])
    return JsonResponse({"ok": True, "url": reverse("ventas:ticket", args=[venta.pk]) + "?nueva=1&volver=" + quote(siguiente, safe="/")})


def _nota_cobro(c, datos):
    """La nota de la venta: la que se escribió o el nombre de la mesa; si se pagó en partes iguales, se anota."""
    nota = str(datos.get("nota") or "").strip() or c.titulo
    partes = entero(datos.get("partes")) or 0
    if 2 <= partes <= 30:
        nota += f" · pagado en {partes} partes iguales"
    return nota[:200]


@permiso_requerido("mesas.atender")
@require_POST
def delivery_nuevo(request):
    from core.models import Ajustes

    if not Ajustes.cargar().delivery_activo:
        messages.error(request, "El delivery no está activado (Datos del negocio).")
        return redirect("mesas:mapa")
    d = request.POST
    try:
        c = abrir_delivery(request.user, d.get("nombre"), d.get("telefono"), d.get("direccion"), d.get("referencia"), d.get("paga_con"),
                           d.get("costo_envio"))
    except MesaError as e:
        messages.error(request, str(e))
        return redirect("mesas:mapa")
    return redirect(reverse("mesas:agregar", args=[c.pk]))


@permiso_requerido("mesas.atender")
def delivery_buscar(request):
    """Por el celular: el cliente y su última dirección, para no volver a preguntarla."""
    tel = "".join(ch for ch in request.GET.get("tel", "") if ch.isdigit())
    if len(tel) < 6:
        return JsonResponse({})
    previo = Cuenta.objects.filter(tipo=Cuenta.Tipo.DELIVERY, telefono__endswith=tel[-9:]).order_by("-abierta_en").first()
    datos = {}
    if previo:
        datos = {"nombre": previo.nombre, "direccion": previo.direccion, "referencia": previo.referencia, "pedidos": Cuenta.objects.filter(
            tipo=Cuenta.Tipo.DELIVERY, telefono=previo.telefono).exclude(estado=Cuenta.Estado.ANULADA).count()}
    from core.permisos import modulo_activo

    if modulo_activo(request.user, "clientes"):
        from clientes.models import Cliente

        cli = Cliente.objects.filter(telefono__endswith=tel[-9:], activo=True).first()
        if cli:
            datos.setdefault("nombre", cli.nombre)
            if not datos.get("direccion"):
                datos["direccion"] = cli.direccion
            saldo = cli.saldo
            if saldo > 0:
                datos["debe"] = f"{saldo:.2f}"
    return JsonResponse(datos)


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def delivery_accion(request, pk):
    c = _cuenta(pk)
    if not c.es_delivery:
        return redirect("mesas:cuenta", pk=pk)
    accion, d = request.POST.get("accion"), request.POST
    try:
        if accion == "datos":
            from django.db import transaction

            with transaction.atomic():
                datos_delivery(c, d.get("nombre"), d.get("telefono"), d.get("direccion"), d.get("referencia"), d.get("paga_con"))
                poner_envio(c, d.get("costo_envio"), request.user)
            messages.success(request, "Datos del delivery guardados.")
        elif accion == "salio":
            salio_delivery(c, d.get("repartidor"))
            messages.success(request, f"{c.titulo}: en camino" + (f" con {c.repartidor}." if c.repartidor else "."))
        elif accion == "entregado":
            entregar_delivery(c)
            c.refresh_from_db()
            if not c.abierta:
                messages.success(request, f"{c.titulo} entregado y cerrado.")
                return redirect("mesas:mapa")
            messages.info(request, f"{c.titulo} entregado. Falta cobrarlo.")
    except MesaError as e:
        messages.error(request, str(e))
    return redirect("mesas:cuenta", pk=pk)


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def liberar(request, pk):
    c = _cuenta(pk)
    try:
        entregar_delivery(c) if c.es_delivery else liberar_mesa(c)
    except MesaError as e:
        messages.error(request, str(e))
        return redirect("mesas:cuenta", pk=pk)
    messages.success(request, f"{c.titulo} {'entregado' if not c.mesa_id else 'liberada'}.")
    return redirect("mesas:mapa")


@permiso_requerido("mesas.atender", "mesas.cobrar")
@require_POST
def anular(request, pk):
    c, _ = _accion(request, pk, lambda c: anular_cuenta(c, request.user, request.POST.get("motivo"), puede(request.user, "mesas.anular")))
    if not c.abierta or Cuenta.objects.get(pk=pk).estado != Cuenta.Estado.ABIERTA:
        messages.success(request, f"{c.titulo} liberada.")
        return redirect("mesas:mapa")
    return redirect("mesas:cuenta", pk=pk)


# --- Configuración ----------------------------------------------------------------

@permiso_requerido("mesas.configurar")
def configurar(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "zona":
            nombre = " ".join(request.POST.get("nombre", "").split())[:40]
            if nombre:
                _, nueva = Zona.objects.get_or_create(nombre=nombre, defaults={"orden": Zona.objects.count() * 10})
                messages.success(request, f"Zona «{nombre}» creada." if nueva else "Esa zona ya existe.")
        elif accion == "lote":
            zona = get_object_or_404(Zona, pk=entero(request.POST.get("zona")))
            desde, hasta = entero(request.POST.get("desde")), entero(request.POST.get("hasta"))
            prefijo = request.POST.get("prefijo", "").strip()[:8]
            capacidad = entero(request.POST.get("capacidad")) or 4
            if desde is None or hasta is None or hasta < desde or hasta - desde > 100:
                messages.error(request, "Revisa los números (máximo 100 mesas a la vez).")
            else:
                creadas = 0
                for n in range(desde, hasta + 1):
                    _, nueva = Mesa.objects.get_or_create(nombre=f"{prefijo}{n}", defaults={"zona": zona, "capacidad": capacidad, "orden": n})
                    creadas += nueva
                messages.success(request, f"Se crearon {creadas} mesas." + (" Algunas ya existían." if creadas < hasta - desde + 1 else ""))
        elif accion == "guardar_zona":
            zona = get_object_or_404(Zona, pk=entero(request.POST.get("pk")))
            filas, error = _filas_zona(zona, request.POST)
            if error:
                messages.error(request, error)
                return _pantalla_configurar(request, {zona.pk: filas})
            _guardar_filas(filas)
            borrar = Mesa.objects.filter(pk=entero(request.POST.get("borrar")), zona=zona).first() if request.POST.get("borrar") else None
            if borrar:
                _borrar_mesa(request, borrar)
            else:
                messages.success(request, f"Zona «{zona.nombre}»: cambios guardados.")
        elif accion == "borrar_zona":
            z = get_object_or_404(Zona, pk=entero(request.POST.get("pk")))
            if z.mesas.exists():
                messages.error(request, "Primero quita o mueve las mesas de esa zona.")
            else:
                z.delete()
                messages.success(request, "Zona eliminada.")
        return redirect("mesas:configurar")
    return _pantalla_configurar(request)


def _pantalla_configurar(request, enviadas=None):
    """Muestra zonas y mesas; `enviadas` = {zona_pk: filas} para volver a mostrar lo que se escribió si hubo un error."""
    enviadas = enviadas or {}
    zonas = list(Zona.objects.prefetch_related("mesas").annotate(n=Count("mesas")))
    for z in zonas:
        z.filas = enviadas.get(z.pk) or [{"mesa": m, "nombre": m.nombre, "capacidad": m.capacidad, "zona": m.zona_id, "activa": m.activa}
                                         for m in z.mesas.all()]
        z.con_error = z.pk in enviadas
    return render(request, "mesas/configurar.html", {"zonas": zonas}, status=400 if enviadas else 200)


def _filas_zona(zona, datos):
    """Lee lo que se escribió para cada mesa de la zona y lo revisa. Devuelve (filas, mensaje de error o None)."""
    zonas = set(Zona.objects.values_list("pk", flat=True))
    filas, errores = [], []
    for m in zona.mesas.all():
        nombre = " ".join(datos.get(f"nombre_{m.pk}", m.nombre).split())[:20]
        zona_id = entero(datos.get(f"zona_{m.pk}"))
        filas.append({"mesa": m, "nombre": nombre, "capacidad": entero(datos.get(f"capacidad_{m.pk}")) or m.capacidad,
                      "zona": zona_id if zona_id in zonas else m.zona_id, "activa": datos.get(f"activa_{m.pk}") == "on"})
        if not nombre:
            errores.append(f"la mesa {m.nombre} quedó sin nombre")
    nombres = [f["nombre"].lower() for f in filas if f["nombre"]]
    repetidos = sorted({f["nombre"] for f in filas if f["nombre"] and nombres.count(f["nombre"].lower()) > 1})
    if repetidos:
        errores.append("hay nombres repetidos en la zona: " + ", ".join(repetidos))
    otras = {n.lower(): n for n in Mesa.objects.exclude(zona=zona).values_list("nombre", flat=True)}
    choques = sorted({otras[f["nombre"].lower()] for f in filas if f["nombre"].lower() in otras})
    if choques:
        errores.append("ya existe en otra zona: " + ", ".join(choques))
    if errores:
        return filas, "No se guardó nada: " + "; ".join(errores) + ". Corrige y vuelve a guardar."
    return filas, None


def _guardar_filas(filas):
    """Guarda todas las mesas juntas. Primero nombres temporales, para poder intercambiar nombres (T1 ↔ T2) sin chocar."""
    from django.db import transaction

    with transaction.atomic():
        cambian = [f for f in filas if f["nombre"] != f["mesa"].nombre]
        for f in cambian:
            Mesa.objects.filter(pk=f["mesa"].pk).update(nombre=f"__{f['mesa'].pk}")
        for f in filas:
            m = f["mesa"]
            m.nombre, m.capacidad, m.zona_id, m.activa = f["nombre"], f["capacidad"], f["zona"], f["activa"]
            m.save()


def _borrar_mesa(request, m):
    if m.cuentas.exists():
        m.activa = False
        m.save(update_fields=["activa"])
        messages.info(request, f"Cambios guardados. La mesa {m.nombre} tiene historial: se desactivó en vez de borrarse.")
    else:
        nombre = m.nombre
        m.delete()
        messages.success(request, f"Cambios guardados y mesa {nombre} eliminada.")


# --- Pantalla de cocina ----------------------------------------------------------

def _area(request):
    a = (request.POST.get("area") or request.GET.get("area") or "COC").upper()
    return a if a in ("COC", "BAR") else "COC"


def _hay_barra():
    from productos.models import Categoria, Producto

    return Categoria.objects.filter(area="BAR", activa=True).exists() or Producto.objects.filter(area="BAR", activo=True).exists()


def _comandas(area="COC"):
    """Pedidos enviados a cocina (o a la barra), agrupados por envío (una comanda = una mesa + una hora de envío)."""
    from datetime import timedelta

    desde = timezone.now() - timedelta(hours=12)
    items = (ItemCuenta.objects.filter(enviado_en__gte=desde, es_envio=False, area=area).exclude(cuenta__estado=Cuenta.Estado.ANULADA)
             .select_related("cuenta__mesa", "cuenta__mozo").order_by("enviado_en", "id"))
    grupos = {}
    for i in items:
        grupos.setdefault((i.cuenta_id, i.enviado_en), []).append(i)
    pendientes, listas = [], []
    hace_rato = timezone.now() - timedelta(minutes=20)
    for (cuenta_id, enviado), lista in grupos.items():
        vigentes = [i for i in lista if not i.anulado]
        if not vigentes:
            continue
        comanda = {"cuenta": lista[0].cuenta, "enviado": enviado, "items": lista, "clave": f"{cuenta_id}-{int(enviado.timestamp() * 1e6)}",
                   "minutos": int((timezone.now() - enviado).total_seconds() // 60), "enviado_iso": enviado.isoformat()}
        if any(i.listo_en is None for i in vigentes):
            pendientes.append(comanda)
        elif max(i.listo_en for i in vigentes) >= hace_rato:
            comanda["listo"] = max(i.listo_en for i in vigentes)
            listas.append(comanda)
    listas.sort(key=lambda c: c["listo"], reverse=True)
    return {"pendientes": pendientes, "listas": listas[:12], "area": area}


@permiso_requerido("mesas.cocina")
def cocina(request):
    area = _area(request)
    datos = _comandas(area)
    if request.htmx:
        return render(request, "mesas/partials/cocina.html", datos)
    return render(request, "mesas/cocina.html", {**datos, "area": area, "hay_barra": _hay_barra()})


@permiso_requerido("mesas.cocina")
@require_POST
def cocina_marcar(request):
    """Marca como listo (o deshace) un plato o una comanda entera."""
    listo = request.POST.get("listo", "1") == "1"
    area = _area(request)
    if request.POST.get("item"):
        items = ItemCuenta.objects.filter(pk=entero(request.POST.get("item")))
    else:
        enviado = parse_datetime(request.POST.get("enviado", "") or "")
        items = ItemCuenta.objects.filter(cuenta_id=entero(request.POST.get("cuenta")), enviado_en=enviado, area=area) if enviado else ItemCuenta.objects.none()
    if listo and request.POST.get("item"):
        it = items.first()
        listo = it is not None and it.listo_en is None  # un plato: alterna
    marcar_listo(list(items), listo)
    if request.htmx:
        return render(request, "mesas/partials/cocina.html", _comandas(area))
    return redirect(reverse("mesas:cocina") + ("?area=BAR" if area == "BAR" else ""))
