from decimal import Decimal

from django import forms

import re

from .models import Area, CERO, Categoria, GrupoOpciones, MovimientoStock, Producto, Variante
from .rubros import etiquetas_variantes

DINERO = {"step": "0.01", "min": "0", "inputmode": "decimal"}
CANTIDAD = {"step": "any", "inputmode": "decimal"}


def _codigo_libre(codigo, excluir_variante=None):
    qs = Variante.objects.filter(codigo=codigo)
    if excluir_variante is not None:
        qs = qs.exclude(pk=excluir_variante.pk)
    otra = qs.select_related("producto").first()
    if otra:
        raise forms.ValidationError(f"Ese código ya lo tiene «{otra.nombre_completo}».")
    return codigo


class ProductoForm(forms.ModelForm):
    codigo = forms.CharField(label="Código / código de barras", max_length=50, required=False,
                             widget=forms.TextInput(attrs={"data-escaner": "1", "autocomplete": "off"}),
                             help_text="Escanéalo con la lectora o con la cámara. Opcional, no se repite.")
    stock_inicial = forms.DecimalField(label="Stock inicial", required=False, min_value=CERO, decimal_places=3,
                                       widget=forms.NumberInput(attrs=CANTIDAD), help_text="Cuánto tienes ahora.")

    class Meta:
        model = Producto
        fields = ["tipo", "nombre", "categoria", "unidad", "precio", "costo", "maneja_stock", "stock_minimo",
                  "duracion_min", "descripcion", "imagen", "activo", "grupos", "area"]
        widgets = {
            "tipo": forms.RadioSelect,
            "precio": forms.NumberInput(attrs=DINERO),
            "costo": forms.NumberInput(attrs=DINERO),
            "stock_minimo": forms.NumberInput(attrs=CANTIDAD),
            "descripcion": forms.Textarea(attrs={"rows": 2}),
            "imagen": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
            "nombre": forms.TextInput(attrs={"autofocus": True}),
            "grupos": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = Categoria.objects.filter(activa=True) | (
            Categoria.objects.filter(pk=self.instance.categoria_id) if self.instance.categoria_id else Categoria.objects.none())
        self.fields["categoria"].empty_label = "Sin categoría"
        self.fields["unidad"].choices = [c for c in self.fields["unidad"].choices if c[0] != "SRV"]
        self.fields["stock_minimo"].required = False  # oculto en servicios
        self.fields["grupos"].queryset = GrupoOpciones.objects.filter(activo=True)
        self.fields["grupos"].label_from_instance = lambda g: f"{g.nombre} ({g.regla.lower()})"
        self.fields["unidad"].required = False
        from core.models import Ajustes

        ajustes = Ajustes.cargar()
        # Tipos que el negocio no usa no se ofrecen (salvo que este producto ya sea de ese tipo)
        ocultos = {Producto.Tipo.SERVICIO: ajustes.usa_servicios, Producto.Tipo.COMBO: ajustes.usa_combos}
        self.fields["tipo"].choices = [(k, v) for k, v in self.fields["tipo"].choices
                                       if ocultos.get(k, True) or self.instance.tipo == k]
        self.solo_un_tipo = len(self.fields["tipo"].choices) == 1
        if ajustes.tiene_modulo("mesas"):
            self.fields["area"].choices = [("", "Como su categoría")] + list(Area.choices)
        else:
            del self.fields["area"]
        self.es_nuevo = self.instance.pk is None
        self.unica = None if self.es_nuevo else self.instance.variante_unica()
        self.con_variantes = not self.es_nuevo and self.instance.tiene_variantes
        if self.con_variantes:
            del self.fields["codigo"]  # cada variante tiene su código
        elif self.unica:
            self.initial["codigo"] = self.unica.codigo
        if not self.es_nuevo:
            del self.fields["stock_inicial"]  # después, el stock solo cambia con movimientos

    def clean_codigo(self):
        codigo = (self.cleaned_data.get("codigo") or "").strip()
        return _codigo_libre(codigo, self.unica) if codigo else ""

    def clean_nombre(self):
        return " ".join(self.cleaned_data["nombre"].split())

    def clean_stock_minimo(self):
        return self.cleaned_data.get("stock_minimo") or CERO

    def clean_unidad(self):
        return self.cleaned_data.get("unidad") or "UND"

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") == Producto.Tipo.SERVICIO:
            datos["maneja_stock"] = False
            datos["stock_inicial"] = None
        if not datos.get("maneja_stock"):
            datos["stock_inicial"] = None
        return datos


class VarianteForm(forms.ModelForm):
    class Meta:
        model = Variante
        fields = ["nombre", "codigo", "precio", "costo", "activa"]
        widgets = {"precio": forms.NumberInput(attrs=DINERO), "costo": forms.NumberInput(attrs=DINERO),
                   "codigo": forms.TextInput(attrs={"data-escaner": "1", "autocomplete": "off"})}

    def __init__(self, *args, ver_costos=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
        if not ver_costos:
            del self.fields["costo"]

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        if self.instance.producto.variantes.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ese producto ya tiene una variante con ese nombre.")
        return nombre

    def clean_codigo(self):
        codigo = (self.cleaned_data.get("codigo") or "").strip()
        return _codigo_libre(codigo, self.instance) if codigo else ""


class GenerarVariantesForm(forms.Form):
    opciones1 = forms.CharField(max_length=300)
    opciones2 = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        e1, ej1, e2, ej2 = etiquetas_variantes()
        self.fields["opciones1"].label = e1
        self.fields["opciones1"].widget.attrs["placeholder"] = ej1
        self.fields["opciones2"].label = f"{e2} (opcional)"
        self.fields["opciones2"].widget.attrs["placeholder"] = ej2 or "Déjalo vacío si no hace falta"
        self.fields["opciones1"].help_text = "Separadas por coma."


class MovimientoForm(forms.Form):
    OPERACIONES = [
        ("ING", "Ingreso: llegó mercadería"),
        ("SAL", "Salida: merma, vencido, uso interno"),
        ("AJU", "Conteo: el stock real es…"),
    ]
    variante = forms.ModelChoiceField(queryset=Variante.objects.none(), label="Variante", empty_label=None)
    operacion = forms.ChoiceField(label="¿Qué pasó?", choices=OPERACIONES, widget=forms.RadioSelect, initial="ING")
    cantidad = forms.DecimalField(label="Cantidad", decimal_places=3, min_value=CERO, widget=forms.NumberInput(attrs=CANTIDAD))
    costo_unitario = forms.DecimalField(label="Costo unitario", required=False, min_value=CERO, decimal_places=2,
                                        widget=forms.NumberInput(attrs=DINERO), help_text="Opcional. Actualiza el costo.")
    referencia = forms.CharField(label="Comprobante / proveedor", max_length=60, required=False,
                                 widget=forms.TextInput(attrs={"placeholder": "Ej.: Factura F001-45, Distribuidora Lima"}))
    nota = forms.CharField(label="Nota", max_length=200, required=False)

    def __init__(self, *args, producto=None, ver_costos=True, **kwargs):
        super().__init__(*args, **kwargs)
        qs = producto.variantes.filter(activa=True)
        self.fields["variante"].queryset = qs
        self.fields["variante"].label_from_instance = lambda v: f"{v.nombre or producto.nombre} (stock: {v.stock.normalize():f})"
        if not producto.tiene_variantes:
            self.fields["variante"].widget = forms.HiddenInput()
            self.initial.setdefault("variante", qs.first())
        if not ver_costos:
            del self.fields["costo_unitario"]

    def clean(self):
        datos = super().clean()
        if datos.get("operacion") in ("ING", "SAL") and datos.get("cantidad") is not None and datos["cantidad"] <= 0:
            self.add_error("cantidad", "Indica una cantidad mayor que cero.")
        return datos


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "area", "orden", "activa"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Ajustes

        if not Ajustes.cargar().tiene_modulo("mesas"):
            del self.fields["area"]

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        if Categoria.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe esa categoría.")
        return nombre


class ListaPreciosForm(forms.ModelForm):
    class Meta:
        from .models import ListaPrecios

        model = ListaPrecios
        fields = ["nombre", "porcentaje", "activa"]
        widgets = {"porcentaje": forms.NumberInput(attrs={"step": "0.5", "min": "0", "max": "99", "inputmode": "decimal"})}

    def clean_nombre(self):
        from .models import ListaPrecios

        nombre = " ".join(self.cleaned_data["nombre"].split())
        if ListaPrecios.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una lista con ese nombre.")
        return nombre

    def clean_porcentaje(self):
        p = self.cleaned_data["porcentaje"]
        if p >= 100:
            raise forms.ValidationError("Tiene que ser menos de 100 %.")
        return p


class PromocionForm(forms.ModelForm):
    dias = forms.TypedMultipleChoiceField(label="Días", required=False, coerce=int, widget=forms.CheckboxSelectMultiple,
                                          help_text="Ninguno marcado = todos los días.")

    class Meta:
        from .models import Promocion

        model = Promocion
        fields = ["nombre", "tipo", "lleva", "paga", "porcentaje", "precio", "productos", "categorias", "desde", "hasta", "dias",
                  "hora_desde", "hora_hasta", "activa"]
        widgets = {
            "tipo": forms.RadioSelect,
            "productos": forms.SelectMultiple(attrs={"size": 8}),
            "categorias": forms.CheckboxSelectMultiple,
            "desde": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "hasta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "hora_desde": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "hora_hasta": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "lleva": forms.NumberInput(attrs={"min": 2, "inputmode": "numeric"}),
            "paga": forms.NumberInput(attrs={"min": 1, "inputmode": "numeric"}),
            "porcentaje": forms.NumberInput(attrs={"min": 1, "max": 99, "step": "0.5", "inputmode": "decimal"}),
            "precio": forms.NumberInput(attrs={"min": 0, "step": "0.10", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Promocion

        self.fields["dias"].choices = Promocion.DIAS
        self.fields["productos"].queryset = Producto.objects.filter(activo=True).order_by("nombre")
        self.fields["productos"].help_text = "Ctrl o Mayús para elegir varios. En el celular, toca cada uno."
        self.fields["categorias"].queryset = Categoria.objects.filter(activa=True)
        self.fields["categorias"].help_text = "Todos los productos de esas categorías entran."

    def clean(self):
        from .models import Promocion

        d = super().clean()
        tipo = d.get("tipo")
        if tipo == Promocion.Tipo.NXM:
            if not d.get("lleva") or d.get("paga") is None or d["lleva"] <= d["paga"] or d["paga"] < 1:
                self.add_error("lleva", "Para 2×1 pon lleva 2 y paga 1 (lleva tiene que ser mayor que paga).")
            d["porcentaje"] = d["precio"] = None
        elif tipo == Promocion.Tipo.PORCENTAJE:
            if not d.get("porcentaje") or not 0 < d["porcentaje"] < 100:
                self.add_error("porcentaje", "Escribe un % entre 1 y 99.")
            d["lleva"] = d["paga"] = d["precio"] = None
        elif tipo == Promocion.Tipo.PRECIO:
            if d.get("precio") is None:
                self.add_error("precio", "Escribe el precio de la promoción.")
            d["lleva"] = d["paga"] = d["porcentaje"] = None
        if not d.get("productos") and not d.get("categorias"):
            self.add_error("productos", "Elige al menos un producto o una categoría.")
        if d.get("hasta") and d.get("desde") and d["hasta"] < d["desde"]:
            self.add_error("hasta", "La fecha final es antes que la inicial.")
        if bool(d.get("hora_desde")) != bool(d.get("hora_hasta")):
            self.add_error("hora_hasta", "Pon las dos horas (de … a …) o ninguna.")
        return d


class ImportarForm(forms.Form):
    archivo = forms.FileField(label="Archivo Excel (.xlsx)", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))

    def clean_archivo(self):
        a = self.cleaned_data["archivo"]
        if not a.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Sube un archivo .xlsx (Excel).")
        if a.size > 5 * 1024 * 1024:
            raise forms.ValidationError("El archivo es muy grande (máximo 5 MB).")
        return a


def decimal_o_none(valor):
    if valor in (None, ""):
        return None
    return Decimal(str(valor))


class GrupoOpcionesForm(forms.ModelForm):
    opciones_texto = forms.CharField(
        label="Opciones", widget=forms.Textarea(attrs={"rows": 7, "placeholder": "Papas fritas *\nArroz\nEnsalada\nHuevo frito | 2.00"}),
        help_text="Una por línea. Si se cobra aparte, ponle el precio después de una barra: «Huevo frito | 2.00». "
                  "Si viene incluida (ya aparece elegida al pedir), ponle un asterisco: «Papas fritas *».")
    productos = forms.ModelMultipleChoiceField(queryset=Producto.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
                                               label="Usar en estos productos")

    class Meta:
        model = GrupoOpciones
        fields = ["nombre", "minimo", "maximo", "orden", "activo", "diario"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["productos"].queryset = Producto.objects.filter(activo=True).order_by("categoria__orden", "nombre")
        if self.instance.pk:
            self.initial["productos"] = list(self.instance.productos.values_list("pk", flat=True))
            self.initial["opciones_texto"] = "\n".join(
                o.nombre + (" *" if o.por_defecto else "") + (f" | {o.precio:.2f}" if o.precio else "") for o in self.instance.opciones.filter(activa=True))

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        if GrupoOpciones.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un grupo con ese nombre.")
        return nombre

    def clean_opciones_texto(self):
        filas, vistos = [], set()
        for n, linea in enumerate(self.cleaned_data["opciones_texto"].splitlines(), start=1):
            linea = linea.strip()
            if not linea:
                continue
            from .servicios import leer_linea_opcion

            try:
                nombre, precio, defecto = leer_linea_opcion(linea)
            except ValueError as e:
                raise forms.ValidationError(f"Línea {n}: {e}.")
            if not nombre:
                raise forms.ValidationError(f"Línea {n}: falta el nombre.")
            if nombre.lower() in vistos:
                raise forms.ValidationError(f"«{nombre}» está repetido.")
            vistos.add(nombre.lower())
            filas.append((nombre, precio, defecto))
        if not filas:
            raise forms.ValidationError("Escribe al menos una opción.")
        return filas

    def clean(self):
        d = super().clean()
        mn, mx, ops = d.get("minimo"), d.get("maximo"), d.get("opciones_texto") or []
        incluidas = sum(1 for o in ops if o[2])
        if mx and incluidas > mx:
            self.add_error("opciones_texto", "Marcaste con * más opciones incluidas de las que se pueden elegir."
                           + (" En un grupo de «elegir 1» solo una puede venir incluida." if mx == 1 else ""))
        if mn is not None and mx and mn > mx:
            self.add_error("minimo", "El mínimo no puede ser mayor que el máximo.")
        if mn and ops and mn > len(ops):
            self.add_error("minimo", "Hay menos opciones que el mínimo a elegir.")
        return d

    def save(self, commit=True):
        from django.db import transaction

        from .models import Opcion

        with transaction.atomic():
            g = super().save()
            actuales = {o.nombre.lower(): o for o in g.opciones.all()}
            usados = set()
            for i, (nombre, precio, defecto) in enumerate(self.cleaned_data["opciones_texto"]):
                o = actuales.get(nombre.lower())
                if o:
                    o.nombre, o.precio, o.orden, o.activa, o.por_defecto = nombre, precio, i, True, defecto
                    o.save()
                else:
                    o = Opcion.objects.create(grupo=g, nombre=nombre, precio=precio, orden=i, por_defecto=defecto)
                usados.add(o.pk)
            g.opciones.exclude(pk__in=usados).update(activa=False)  # no se borran: ya pueden estar en pedidos
            g.productos.set(self.cleaned_data["productos"])
        return g
