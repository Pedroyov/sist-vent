from urllib.parse import quote

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
    f = ClienteForm(request.POST or None, instance=cliente, puede_limite=puede(request.user, "clientes.limite"))
    if request.method == "POST" and f.is_valid():
        c = f.save()
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
    con_factura = [d for d in pendientes if d["comprobante"]]
    vencido = sum((d["vencido"] for d in pendientes), 0)
    texto = (f"Hola {c.nombre.split()[0].title()}, te saludamos de {negocio.nombre_mostrar}. "
             f"Te recordamos que tienes un saldo pendiente de S/ {saldo:.2f}.")
    if con_factura:
        texto += " Facturas: " + "; ".join(f"{d['comprobante'].numero_str} S/ {d['pendiente']:.2f}"
                                           + (f" (vence {d['vence']:%d/%m})" if d["vence"] else "") for d in con_factura) + "."
    texto += " ¡Gracias!"
    return render(request, "clientes/detalle.html", {
        "c": c, "saldo": saldo, "movimientos": estado_de_cuenta(c, 100),
        "compras": c.ventas.select_related("usuario").prefetch_related("pagos").order_by("-fecha")[:15],
        "form_abono": AbonoForm(initial={"monto": saldo if saldo > 0 else None, "metodo": "EFE"}),
        "wa": f"https://wa.me/{c.whatsapp}?text={quote(texto)}" if c.whatsapp else "",
        "anulados": c.abonos.filter(anulado=True)[:10],
        "pendientes": pendientes, "con_factura": bool(con_factura), "vencido": vencido,
        **_cobranzas(request.user, c),
    })


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
            a = registrar_abono(c, f.cleaned_data["monto"], f.cleaned_data["metodo"], request.user, f.cleaned_data["nota"])
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
    clientes = con_saldo(qs).order_by("nombre")[:10]
    return JsonResponse({"resultados": [
        {"id": c.pk, "n": c.nombre, "doc": c.documento, "num": c.numero_documento, "dir": c.direccion,
         "saldo": f"{c.fiado - c.abonado:.2f}", "limite": f"{c.limite_credito:.2f}"}
        for c in clientes]})
