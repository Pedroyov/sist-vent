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
        ("Bebidas", "Gaseosa Coca-Cola", "3.50", "2.40", 0, "UND", "", ("500 ml, 1.5 L, 3 L", "")),
        ("Abarrotes", "Arroz extra a granel", "4.20", "3.50", "50.5", "KG", "", None),
        ("Abarrotes", "Azúcar rubia a granel", "3.80", "3.10", "8", "KG", "", None),
        ("Abarrotes", "Aceite Primor 1 L", "11.50", "9.40", 12, "UND", "7751271101237", None),
        ("Lácteos y embutidos", "Leche Gloria azul 400 g", "4.30", "3.60", 3, "UND", "7751271201234", None),
        ("Snacks y golosinas", "Galleta Soda Field", "0.80", "0.55", 40, "UND", "", None),
        ("Limpieza", "Detergente Bolívar 500 g", "6.90", "5.50", 10, "UND", "", None),
    ],
    Rubro.RESTAURANTE: [
        ("Platos de fondo", "Pollo a la brasa", "18.00", "9.00", None, "UND", "", ("1/4, 1/2, Entero", "")),
        ("Platos de fondo", "Lomo saltado", "22.00", "11.00", None, "UND", "", None),
        ("Entradas", "Papa a la huancaína", "12.00", "4.00", None, "UND", "", None),
        ("Menú del día", "Menú ejecutivo", "15.00", "7.00", None, "UND", "", None),
        ("Bebidas", "Chicha morada", "6.00", "1.50", None, "UND", "", ("Vaso, Jarra 1 L", "")),
        ("Bebidas", "Inca Kola 500 ml", "4.00", "1.80", 24, "UND", "", "stock"),
        ("Postres", "Mazamorra morada", "5.00", "1.50", None, "UND", "", None),
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
            o1, o2 = extra
            generar_variantes(p, o1 or o2, o2 if o1 else "")
            variantes = list(p.variantes.all())
            if p.nombre.startswith("Pollo"):  # precios por tamaño
                for v, pr in zip(variantes, ("18.00", "32.00", "60.00")):
                    v.precio = Decimal(pr)
                    v.save(update_fields=["precio"])
            if p.nombre.startswith("Gaseosa Coca"):
                for v, pr in zip(variantes, ("3.50", "6.50", "12.00")):
                    v.precio = Decimal(pr)
                    v.save(update_fields=["precio"])
            if p.nombre == "Chicha morada":
                variantes[1].precio = Decimal("15.00")
                variantes[1].save(update_fields=["precio"])
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
    return Producto.objects.count()
