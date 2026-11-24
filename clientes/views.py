from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from core.permisos import permiso_requerido, puede
from core.utils import enlace_whatsapp

from .forms import AbonoForm, ClienteForm
from .models import Abono, Cliente
from .servicios import ClienteError, anular_abono, con_saldo, deudas, estado_de_cuenta, marcar_incobrable, registrar_abono, total_por_cobrar


def _filtrar(request):
    q = request.GET.get("q", "").strip()
    filtro = request.GET.get("ver", "")
    clientes = con_saldo(Cliente.objects.all()).annotate(saldo_calc=F("fiado") - F("abonado"))
    for palabra in q.split():
        clientes = clientes.filter(Q(nombre__icontains=palabra) | Q(numero_documento__icontains=palabra) | Q(telefono__icontains=palabra))
    if filtro == "deben":
        clientes = clientes.filter(saldo_calc__gt=0).order_by("-saldo_calc")
    elif request.GET.get("lista", "").isdigit():
        clientes = clientes.filter(lista_id=int(request.GET["lista"]), activo=True)
        filtro = "lista"
    elif filtro == "vencido":
        from .servicios import vencidos

        clientes = clientes.filter(pk__in=list(vencidos())).order_by("-saldo_calc")
    elif filtro == "inactivos":
        clientes = clientes.filter(activo=False)
    else:
        clientes = clientes.filter(activo=True)
    return clientes, {"q": q, "ver": filtro}


@permiso_requerido("clientes.ver")
def lista(request):
    clientes, f = _filtrar(request)
    if request.GET.get("excel"):
        return _excel(clientes)
    pagina = Paginator(clientes, 30).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    contexto = {"pagina": pagina, "f": f, "query": query}
    if request.htmx:
        return render(request, "clientes/partials/tabla.html", contexto)
    contexto["por_cobrar"] = total_por_cobrar()
    contexto["n_deben"] = con_saldo().filter(fiado__gt=F("abonado")).count()
    return render(request, "clientes/lista.html", contexto)


def _excel(clientes):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core.excel import a_bytes

    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(["Documento", "Número", "Nombre", "Celular", "Correo", "Dirección", "Límite de fiado", "Debe"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for c in clientes[:20000]:
        ws.append([c.get_tipo_documento_display(), c.numero_documento, c.nombre, c.telefono, c.email, c.direccion,
                   float(c.limite_credito), float(c.saldo_calc)])
    resp = HttpResponse(a_bytes(wb), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = content_disposition_header(True, f"clientes_{timezone.localdate():%Y%m%d}.xlsx")
    return resp


@permiso_requerido("clientes.editar")
def form(request, pk=None):
    cliente = get_object_or_404(Cliente, pk=pk) if pk else None
    f = ClienteForm(request.POST or None, instance=cliente, puede_limite=puede(request.user, "clientes.limite"),
                    puede_precio=puede(request.user, "ventas.precio"))
    if request.method == "POST" and f.is_valid():
        from core.bitacora import anotar, cambios_form

        limite = cambios_form(f, ["limite_credito"]) if cliente else {}
        plazo_ = cambios_form(f, ["dias_credito"]) if cliente else {}
        lista_ = cambios_form(f, ["lista"])
        c = f.save()
        if lista_ and (cliente or c.lista_id):
            antes, despues = lista_["lista"]
            anotar("cliente.lista", f"Lista de precios de {c}: {antes or 'precio normal'} → {despues or 'precio normal'}", objeto=c,
                   antes={"lista": str(antes or "")}, despues={"lista": str(despues or "")})
        if plazo_:
            antes, despues = plazo_["dias_credito"]
            nombre = lambda v: "el general" if v in (None, "", "None") else f"{v} días"
            anotar("cliente.plazo", f"Plazo del fiado de {c}: {nombre(antes)} → {nombre(despues)}", objeto=c,
                   antes={"dias": antes}, despues={"dias": despues})
        if limite:
            anotar("cliente.limite", f"Límite de fiado de {c}: S/ {limite['limite_credito'][0]} → S/ {limite['limite_credito'][1]}",
                   objeto=c, antes={"limite": limite["limite_credito"][0]}, despues={"limite": limite["limite_credito"][1]})
        messages.success(request, f"Cliente «{c.nombre}» guardado.")
        return redirect("clientes:detalle", pk=c.pk)
    url = reverse("clientes:detalle", args=[cliente.pk]) if cliente else reverse("clientes:lista")
    return render(request, "core/form.html", {
        "form": f, "titulo": f"Editar {cliente.nombre}" if cliente else "Nuevo cliente", "cancelar": url,
        "breadcrumb": [("Clientes", reverse("clientes:lista"))],
        "ayuda": "El RUC se valida con su dígito verificador. Para facturas, registra la razón social y la dirección fiscal."})


@permiso_requerido("clientes.ver")
def detalle(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    saldo = c.saldo
    from core.models import Ajustes

    negocio = Ajustes.cargar()
    pendientes = [d for d in deudas(c) if d["pendiente"] > 0]
    vencido = sum((d["vencido"] for d in pendientes), 0)
    texto = (f"Hola {c.nombre.split()[0].title()}, te saludamos de {negocio.nombre_mostrar}. "
             f"Te recordamos que tienes un saldo pendiente de S/ {saldo:.2f}")
    texto += f", de los cuales S/ {vencido:.2f} ya venció." if vencido else "."
    if any(d["vence"] for d in pendientes):
        def linea(d):
            doc = d["comprobante"].numero_str if d["comprobante"] else f"compra del {timezone.localtime(d['venta'].fecha):%d/%m}"
            cuando = f" (venció el {d['vence']:%d/%m})" if d["vencido"] else f" (vence el {d['vence']:%d/%m})" if d["vence"] else ""
            return f"{doc} S/ {d['pendiente']:.2f}{cuando}"
        texto += " Detalle: " + "; ".join(linea(d) for d in pendientes[:6]) + ("; …" if len(pendientes) > 6 else "") + "."
    texto += " ¡Gracias!"
    return render(request, "clientes/detalle.html", {
        "c": c, "saldo": saldo, "movimientos": estado_de_cuenta(c, 100),
        "compras": c.ventas.select_related("usuario").prefetch_related("pagos").order_by("-fecha")[:15],
        "form_abono": AbonoForm(initial={"monto": saldo if saldo > 0 else None, "metodo": "EFE"}),
        "wa": enlace_whatsapp(c.telefono, texto),
        "anulados": c.abonos.filter(anulado=True)[:10],
        "pendientes": pendientes, "con_plazo": any(d["vence"] for d in pendientes), "vencido": vencido,
        **_cobranzas(request.user, c),
        "h": _historial(c),
        **_saldo_a_favor(c),
        "historial": _bitacora(request.user, c), "historial_tipo": "cliente", "historial_id": c.pk,
    })


def _saldo_a_favor(c):
    from .saldo import por_vencer, saldo_a_favor

    movimientos = list(c.saldo_movimientos.select_related("usuario", "venta")[:15])
    return {"favor": saldo_a_favor(c) if movimientos else 0, "mov_saldo": movimientos, "hoy": timezone.localdate(),
            "vence_pronto": por_vencer(c) if movimientos else None}


@permiso_requerido("ventas.devolver")
@require_POST
def devolver_saldo(request, pk):
    from .saldo import SaldoError, reintegrar

    c = get_object_or_404(Cliente, pk=pk)
    try:
        m = reintegrar(c, request.POST.get("monto"), request.user, request.POST.get("motivo"))
        messages.success(request, f"Se devolvieron S/ {m.monto:.2f} en efectivo a {c.nombre}.")
    except SaldoError as e:
        messages.error(request, str(e))
    return redirect("clientes:detalle", pk=pk)


def _bitacora(usuario, c):
    """Cambios de límite, ventas sobre el límite, incobrables: solo lo ve Administración."""
    from core.permisos import acceso_total

    if not acceso_total(usuario):
        return []
    from core.bitacora import de_objetos

    return de_objetos([c])


def _historial(c):
    """Lo que hizo en todo el negocio (delivery, reservas, citas), con el mismo cálculo que usan esos módulos."""
    from .servicios import historial

    h = historial(cliente=c) if c.telefono else {}
    return h if any(h.get(k) for k in ("pedidos", "reservas", "citas")) else {}


def _cobranzas(user, c):
    """Resumen de sus mensualidades para la ficha (si el módulo Cobranzas está activo)."""
    if not puede(user, "cobranzas.ver"):
        return {}
    from django.db.models import Sum

    from cobranzas.models import Inscripcion
    from cobranzas.servicios import pendientes

    return {"inscripciones": [str(i) for i in c.inscripciones.filter(estado=Inscripcion.Estado.ACTIVA).select_related("plan", "cliente")],
            "cuotas_debe": pendientes(c).aggregate(t=Sum("falta"))["t"] or 0}


@permiso_requerido("clientes.limite")
@require_POST
def incobrable(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    try:
        a = marcar_incobrable(c, request.POST.get("monto"), request.POST.get("motivo"), request.user)
        messages.success(request, f"S/ {a.monto:.2f} marcados como incobrables. Ahora debe S/ {c.saldo:.2f}.")
    except ClienteError as e:
        messages.error(request, str(e))
    return redirect("clientes:detalle", pk=pk)


@permiso_requerido("clientes.cobrar")
@require_POST
def abonar(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    f = AbonoForm(request.POST)
    if f.is_valid():
        try:
            a = registrar_abono(c, f.cleaned_data["monto"], f.cleaned_data["metodo"], request.user, f.cleaned_data["nota"],
                                f.cleaned_data["referencia"])
            messages.success(request, f"Pago de S/ {a.monto:.2f} registrado. Ahora debe S/ {c.saldo:.2f}.")
            return redirect(reverse("clientes:detalle", args=[pk]) + f"?imprimir={a.pk}")
        except ClienteError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Revisa el monto.")
    return redirect("clientes:detalle", pk=pk)


@permiso_requerido("clientes.limite")
@require_POST
def anular(request, pk):
    a = get_object_or_404(Abono, pk=pk)
    try:
        anular_abono(a, request.user, request.POST.get("motivo"))
        messages.success(request, f"Pago {a.numero} anulado.")
    except ClienteError as e:
        messages.error(request, str(e))
    return redirect("clientes:detalle", pk=a.cliente_id)


@permiso_requerido("clientes.ver")
def imprimir(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    abono = c.abonos.filter(pk=request.GET.get("pago") or 0).first()
    return render(request, "impresion/estado_cuenta.html", {"c": c, "saldo": c.saldo, "abono": abono,
                                                             "movimientos": estado_de_cuenta(c, 15)})


@permiso_requerido("clientes.ver", "ventas.vender", "mesas.cobrar", "cobranzas.inscribir")
def buscar(request):
    """Para el cuadro de cobro: busca por nombre, DNI o RUC."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"resultados": []})
    qs = Cliente.objects.filter(activo=True)
    for palabra in q.split():
        qs = qs.filter(Q(nombre__icontains=palabra) | Q(numero_documento__startswith=palabra))
    from .saldo import saldo_a_favor
    from .servicios import vencidos

    clientes = list(con_saldo(qs).select_related("lista").order_by("nombre")[:10])
    from productos.precios import activa as con_listas

    listas = con_listas()
    atrasos = vencidos([c for c in clientes if c.fiado > c.abonado])
    return JsonResponse({"resultados": [
        {"id": c.pk, "n": c.nombre, "doc": c.documento, "num": c.numero_documento, "dir": c.direccion, "tel": c.telefono,
         "saldo": f"{c.fiado - c.abonado:.2f}", "limite": f"{c.limite_credito:.2f}", "favor": f"{saldo_a_favor(c):.2f}",
         "vencido": f"{atrasos[c.pk]['monto']:.2f}" if c.pk in atrasos else "0.00",
         "lista": c.lista_id if listas and c.lista and c.lista.activa else None}
        for c in clientes]})


@permiso_requerido("clientes.ver", "delivery.atender", "reservas.gestionar", "citas.gestionar", "citas.agendar_propias",
                   "cobranzas.inscribir", "ventas.vender")
def celular(request):
    """Por el celular: quién es y todo lo que hizo (pedidos, reservas, citas, si no vino, si debe). Lo usan todos los módulos."""
    from django.http import JsonResponse

    from .servicios import historial

    tel = request.GET.get("tel", "")
    if len("".join(c for c in tel if c.isdigit())) < 6:
        return JsonResponse({})
    datos = historial(tel)
    if not puede(request.user, "clientes.ver", "delivery.atender"):
        datos.pop("debe", None)  # lo que debe solo lo ve quien ve clientes
    return JsonResponse(datos)
