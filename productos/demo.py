"""Catálogos de ejemplo por rubro (los usa python manage.py datos_demo)."""
from decimal import Decimal

from core.models import Rubro

from .models import Categoria, MovimientoStock, Producto, Variante
from .servicios import asegurar_variante_unica, generar_variantes, mover_stock

NEGOCIOS = {
    Rubro.TIENDA: ("Bodega Doña Rosa", "Todo lo que necesitas, cerca de ti"),
    Rubro.RESTAURANTE: ("Pollería El Buen Sabor", "Sabor de casa"),
    Rubro.ROPA: ("Moda Urbana", "Viste a tu estilo"),
    Rubro.LIBRERIA: ("Librería El Estudiante", "Todo para el cole y la oficina"),
    Rubro.PELUQUERIA: ("Estilo & Belleza", "Peluquería y spa"),
}

# (categoría, nombre, precio, costo, stock, unidad, código, {opciones: (lista1, lista2)} o servicio en minutos)
CATALOGOS = {
    Rubro.TIENDA: [
        ("Bebidas", "Inca Kola 500 ml", "2.50", "1.80", 48, "UND", "7750182001236", None),
        ("Bebidas", "Agua San Luis sin gas 625 ml", "1.50", "0.90", 60, "UND", "7751271011237", None),
        ("Bebidas", "Gaseosa Coca-Cola", "3.50", "2.40", 0, "UND", "", ("500 ml, 1.5 L, 3 L", "", "3.50, 6.50, 12.00")),
        ("Abarrotes", "Arroz extra a granel", "4.20", "3.50", "50.5", "KG", "", None),
        ("Abarrotes", "Azúcar rubia a granel", "3.80", "3.10", "8", "KG", "", None),
        ("Abarrotes", "Aceite Primor 1 L", "11.50", "9.40", 12, "UND", "7751271101237", None),
        ("Lácteos y embutidos", "Leche Gloria azul 400 g", "4.30", "3.60", 3, "UND", "7751271201234", None),
        ("Snacks y golosinas", "Galleta Soda Field", "0.80", "0.55", 40, "UND", "", None),
        ("Limpieza", "Detergente Bolívar 500 g", "6.90", "5.50", 10, "UND", "", None),
    ],
    Rubro.RESTAURANTE: [
        ("Entradas", "Papa a la huancaína", "12.00", "3.50", None, "UND", "", None),
        ("Entradas", "Causa limeña de pollo", "14.00", "4.50", None, "UND", "", None),
        ("Entradas", "Tequeños con guacamole", "15.00", "5.00", None, "UND", "", None),
        ("Entradas", "Anticuchos de corazón", "18.00", "7.00", None, "UND", "", None),
        ("Entradas", "Choclo con queso", "10.00", "3.50", None, "UND", "", None),
        ("Marinos", "Ceviche", "28.00", "11.00", None, "UND", "", ("Pescado, Mixto", "", "28, 35")),
        ("Marinos", "Leche de tigre", "15.00", "5.00", None, "UND", "", None),
        ("Marinos", "Jalea mixta", "38.00", "16.00", None, "UND", "", None),
        ("Marinos", "Arroz con mariscos", "32.00", "13.00", None, "UND", "", None),
        ("Platos de fondo", "Lomo saltado", "28.00", "12.00", None, "UND", "", None),
        ("Platos de fondo", "Ají de gallina", "22.00", "8.00", None, "UND", "", None),
        ("Platos de fondo", "Arroz chaufa", "20.00", "7.00", None, "UND", "", ("Pollo, Carne, Mixto", "", "20, 24, 26")),
        ("Platos de fondo", "Tallarines verdes con bistec", "26.00", "10.00", None, "UND", "", None),
        ("Platos de fondo", "Seco de res con frejoles", "26.00", "10.00", None, "UND", "", None),
        ("Platos de fondo", "Bistec a lo pobre", "30.00", "13.00", None, "UND", "", None),
        ("Platos de fondo", "Chicharrón de cerdo", "28.00", "11.00", None, "UND", "", None),
        ("Pollos y parrillas", "Pollo a la brasa", "18.00", "9.00", None, "UND", "", ("1/4, 1/2, Entero", "", "18, 32, 60")),
        ("Pollos y parrillas", "Combo familiar", "75.00", "38.00", None, "UND", "", None),
        ("Pollos y parrillas", "Parrilla personal", "45.00", "20.00", None, "UND", "", None),
        ("Pollos y parrillas", "Alitas BBQ", "18.00", "7.00", None, "UND", "", ("6 unidades, 12 unidades", "", "18, 32")),
        ("Pollos y parrillas", "Salchipapa", "12.00", "4.00", None, "UND", "", None),
        ("Sopas", "Caldo de gallina", "18.00", "6.00", None, "UND", "", None),
        ("Sopas", "Parihuela", "35.00", "15.00", None, "UND", "", None),
        ("Sopas", "Chupe de camarones", "42.00", "20.00", None, "UND", "", None),
        ("Menú del día", "Menú ejecutivo", "15.00", "7.00", None, "UND", "", None),
        ("Menú del día", "Menú económico", "10.00", "5.00", None, "UND", "", None),
        ("Bebidas", "Chicha morada", "6.00", "1.50", None, "UND", "", ("Vaso, Jarra 1 L", "", "6, 15")),
        ("Bebidas", "Limonada", "6.00", "1.50", None, "UND", "", ("Vaso, Jarra 1 L", "", "6, 16")),
        ("Bebidas", "Maracuyá", "7.00", "2.00", None, "UND", "", ("Vaso, Jarra 1 L", "", "7, 17")),
        ("Bebidas", "Inca Kola 500 ml", "4.00", "1.80", 36, "UND", "7750182001236", None),
        ("Bebidas", "Coca-Cola 500 ml", "4.00", "1.80", 30, "UND", "7750182002233", None),
        ("Bebidas", "Inca Kola 1.5 L", "9.00", "5.00", 12, "UND", "7750182003230", None),
        ("Bebidas", "Agua San Luis 625 ml", "3.00", "0.90", 24, "UND", "", None),
        ("Bebidas", "Cerveza Cusqueña 620 ml", "12.00", "6.50", 48, "UND", "", None),
        ("Bebidas", "Cerveza Pilsen 630 ml", "10.00", "5.50", 48, "UND", "", None),
        ("Bebidas", "Pisco sour", "18.00", "6.00", None, "UND", "", None),
        ("Bebidas", "Chilcano de pisco", "16.00", "5.00", None, "UND", "", None),
        ("Bebidas", "Café pasado", "5.00", "1.00", None, "UND", "", None),
        ("Bebidas", "Infusión", "3.00", "0.40", None, "UND", "", None),
        ("Postres", "Mazamorra morada", "5.00", "1.50", None, "UND", "", None),
        ("Postres", "Arroz con leche", "5.00", "1.50", None, "UND", "", None),
        ("Postres", "Suspiro a la limeña", "9.00", "3.00", None, "UND", "", None),
        ("Postres", "Picarones", "12.00", "3.50", None, "UND", "", None),
        ("Postres", "Helado de lúcuma", "8.00", "3.00", None, "UND", "", None),
        ("Extras", "Porción de papas fritas", "8.00", "2.50", None, "UND", "", None),
        ("Extras", "Porción de arroz", "5.00", "1.00", None, "UND", "", None),
        ("Extras", "Taper para llevar", "1.00", "0.40", 200, "UND", "", None),
    ],
    Rubro.ROPA: [
        ("Polos", "Polo básico algodón", "29.90", "15.00", 3, "UND", "", ("S, M, L, XL", "Negro, Blanco")),
        ("Pantalones", "Jean clásico", "89.90", "45.00", 2, "UND", "", ("28, 30, 32, 34", "")),
        ("Casacas", "Casaca jean", "129.90", "65.00", 2, "UND", "", ("S, M, L", "")),
        ("Calzado", "Zapatillas urbanas", "149.90", "80.00", 1, "PAR", "", ("38, 39, 40, 41, 42", "")),
        ("Accesorios", "Gorra bordada", "35.00", "12.00", 10, "UND", "", None),
        ("Accesorios", "Medias pack x3", "19.90", "8.00", 15, "PAQ", "", None),
    ],
    Rubro.LIBRERIA: [
        ("Cuadernos", "Cuaderno Standford A4 cuadriculado 100 h", "6.50", "4.20", 60, "UND", "7751493001234", None),
        ("Cuadernos", "Cuaderno Loro A4 rayado 80 h", "4.50", "2.90", 40, "UND", "", None),
        ("Lápices y lapiceros", "Lapicero Faber-Castell 032", "1.00", "0.50", 100, "UND", "", ("", "Azul, Negro, Rojo")),
        ("Lápices y lapiceros", "Lápiz Mongol N° 2", "1.00", "0.55", 5, "UND", "", None),
        ("Papelería", "Papel bond A4 Atlas x 500", "22.00", "17.50", 10, "PAQ", "", None),
        ("Arte y manualidades", "Plumones Jumbo x 12", "12.00", "7.50", 8, "CAJ", "", None),
        ("Copias e impresiones", "Copia B/N", "0.10", None, None, "SRV", "", 1),
        ("Copias e impresiones", "Impresión a color A4", "1.00", None, None, "SRV", "", 2),
    ],
    Rubro.PELUQUERIA: [
        ("Cortes", "Corte de cabello", "25.00", None, None, "SRV", "", ("Niño, Adulto", "")),
        ("Cortes", "Corte + barba", "35.00", None, None, "SRV", "", 45),
        ("Coloración", "Tinte completo", "90.00", None, None, "SRV", "", 120),
        ("Uñas", "Manicure", "20.00", None, None, "SRV", "", 40),
        ("Uñas", "Pedicure", "30.00", None, None, "SRV", "", 50),
        ("Productos de venta", "Shampoo profesional 500 ml", "45.00", "28.00", 6, "UND", "", None),
        ("Productos de venta", "Cera para cabello", "25.00", "14.00", 2, "UND", "", None),
    ],
}


def opciones_demo(producto, azar=None):
    """Para pedidos de ejemplo: la primera opción de cada grupo obligatorio y, a veces, algún adicional."""
    ids = []
    for g in producto.grupos.filter(activo=True).prefetch_related("opciones"):
        ops = [o for o in g.opciones.all() if o.activa and not o.agotada]
        if not ops:
            continue
        if g.minimo:
            ids += [o.pk for o in (azar.sample(ops, g.minimo) if azar else ops[:g.minimo])]
        elif azar and azar.random() < .35:
            ids.append(azar.choice(ops).pk)
    return ids


def _opciones_restaurante():
    from .models import GrupoOpciones, Opcion
    from .rubros import GRUPOS

    grupos = {}
    for i, (nombre, mn, mx, ops) in enumerate(GRUPOS[Rubro.RESTAURANTE]):
        g = GrupoOpciones.objects.create(nombre=nombre, minimo=mn, maximo=mx, orden=i * 10)
        for j, linea in enumerate(ops):
            n, _, pr = linea.partition("|")
            Opcion.objects.create(grupo=g, nombre=n, precio=Decimal(pr or "0"), orden=j)
        grupos[nombre] = g
    frias = ["Inca Kola 500 ml", "Coca-Cola 500 ml", "Inca Kola 1.5 L", "Agua San Luis 625 ml", "Cerveza Cusqueña 620 ml", "Cerveza Pilsen 630 ml"]
    usos = {"Lomo saltado": ["Término de la carne", "Adicionales"], "Bistec a lo pobre": ["Término de la carne", "Adicionales"],
            "Parrilla personal": ["Término de la carne", "Acompañamiento", "Cremas"],
            "Pollo a la brasa": ["Acompañamiento", "Cremas", "Adicionales"], "Combo familiar": ["Cremas"],
            "Alitas BBQ": ["Acompañamiento", "Cremas"], "Salchipapa": ["Cremas", "Adicionales"],
            "Ceviche": ["Picante"], "Leche de tigre": ["Picante"], "Jalea mixta": ["Picante", "Cremas"],
            "Arroz chaufa": ["Adicionales"], "Tallarines verdes con bistec": ["Adicionales"],
            "Menú ejecutivo": ["Adicionales"], "Menú económico": ["Adicionales"], **{n: ["Temperatura"] for n in frias}}
    for nombre, gs in usos.items():
        p = Producto.objects.filter(nombre=nombre).first()
        if p:
            p.grupos.set([grupos[g] for g in gs])


def cargar_catalogo(rubro, usuario=None):
    """Crea el catálogo de ejemplo si todavía no hay productos. Devuelve cuántos productos hay."""
    if Producto.objects.exists():
        return Producto.objects.count()
    for orden, item in enumerate(CATALOGOS.get(rubro, CATALOGOS[Rubro.TIENDA])):
        cat_nombre, nombre, precio, costo, stock, unidad, codigo, extra = item
        cat, _ = Categoria.objects.get_or_create(nombre=cat_nombre, defaults={"orden": orden * 10})
        servicio = unidad == "SRV"
        maneja = not servicio and (stock is not None)
        p = Producto.objects.create(
            nombre=nombre, categoria=cat, precio=Decimal(precio), costo=Decimal(costo) if costo else None,
            unidad=unidad, tipo="S" if servicio else "P", maneja_stock=maneja,
            stock_minimo=(Decimal("1") if isinstance(extra, tuple) else Decimal("5")) if maneja else 0, duracion_min=extra if isinstance(extra, int) else None,
        )
        if isinstance(extra, tuple):
            o1, o2, *precios = extra
            generar_variantes(p, o1 or o2, o2 if o1 else "")
            variantes = list(p.variantes.all())
            if precios:  # precio de cada tamaño, en el mismo orden
                for v, pr in zip(variantes, precios[0].split(",")):
                    v.precio = Decimal(pr.strip())
                    v.save(update_fields=["precio"])
        else:
            variantes = [asegurar_variante_unica(p)]
            if codigo:
                variantes[0].codigo = codigo
                variantes[0].save(update_fields=["codigo"])
        if maneja:
            for i, v in enumerate(variantes):
                cantidad = Decimal(str(stock)) + (i % 3)
                if cantidad:
                    mover_stock(v, cantidad, MovimientoStock.Tipo.INICIAL, usuario, "Datos de ejemplo",
                                costo_unitario=p.costo)
    if rubro == Rubro.RESTAURANTE:
        _opciones_restaurante()
    return Producto.objects.count()


def marcar_agotados_demo():
    """Lo que se acabó hoy (se llama al final, después de las ventas de ejemplo)."""
    from .models import Opcion
    from .servicios import marcar_agotado

    for p in Producto.objects.filter(nombre="Chupe de camarones"):
        marcar_agotado(p)
    for o in Opcion.objects.filter(nombre="Yuca frita"):
        marcar_agotado(o)
