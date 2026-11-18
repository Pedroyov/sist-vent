"""Catálogos de ejemplo por rubro (los usa python manage.py datos_demo)."""
from decimal import Decimal

from core.models import Rubro

from .models import area_sugerida, Categoria, MovimientoStock, Producto, Variante
from .servicios import asegurar_variante_unica, generar_variantes, leer_linea_opcion, mover_stock

NEGOCIOS = {
    Rubro.TIENDA: ("Bodega Doña Rosa", "Todo lo que necesitas, cerca de ti"),
    Rubro.RESTAURANTE: ("Pollería El Buen Sabor", "Sabor de casa"),
    Rubro.ROPA: ("Moda Urbana", "Viste a tu estilo"),
    Rubro.LIBRERIA: ("Librería El Estudiante", "Todo para el cole y la oficina"),
    Rubro.PELUQUERIA: ("Estilo & Belleza", "Peluquería y spa"),
    Rubro.ACADEMIA: ("Centro Vida Activa", "Gimnasio, natación e idiomas"),
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
        ("Bebidas", "Cerveza Pilsen 630 ml", "7.50", "5.80", 24, "UND", "", None),
        ("Bebidas", "Agua Cielo 2.5 L", "3.50", "2.40", 12, "UND", "", None),
        ("Bebidas", "Jugo Frugos durazno 1 L", "4.50", "3.20", 10, "UND", "", None),
        ("Bebidas", "Energizante Volt 300 ml", "2.00", "1.30", 30, "UND", "", None),
        ("Abarrotes", "Fideos Don Vittorio spaghetti 500 g", "3.90", "2.90", 20, "UND", "", None),
        ("Abarrotes", "Atún Florida 170 g", "6.50", "5.10", 15, "UND", "", None),
        ("Abarrotes", "Avena Quaker 900 g", "9.90", "7.80", 6, "UND", "", None),
        ("Abarrotes", "Lentejas a granel", "7.50", "6.00", "10", "KG", "", None),
        ("Abarrotes", "Huevos a granel", "9.50", "8.00", "6", "KG", "", None),
        ("Abarrotes", "Sal de mesa 1 kg", "1.80", "1.20", 12, "UND", "", None),
        ("Panadería", "Pan francés", "0.30", "0.18", 100, "UND", "", None),
        ("Lácteos y embutidos", "Yogurt Gloria fresa 1 L", "7.20", "5.80", 8, "UND", "", None),
        ("Lácteos y embutidos", "Mantequilla Laive 200 g", "8.90", "7.00", 6, "UND", "", None),
        ("Lácteos y embutidos", "Queso fresco", "18.00", "14.00", "2.5", "KG", "", None),
        ("Lácteos y embutidos", "Jamonada", "22.00", "17.00", "1.5", "KG", "", None),
        ("Snacks y golosinas", "Papas Lay's clásicas 42 g", "2.00", "1.40", 24, "UND", "", None),
        ("Snacks y golosinas", "Chocolate Sublime", "1.50", "1.00", 50, "UND", "", None),
        ("Snacks y golosinas", "Galleta Casino menta", "1.00", "0.70", 30, "UND", "", None),
        ("Snacks y golosinas", "Caramelos de limón", "0.10", "0.05", 300, "UND", "", None),
        ("Limpieza", "Lejía Clorox 1 L", "4.50", "3.30", 10, "UND", "", None),
        ("Limpieza", "Papel higiénico x 4", "6.50", "5.00", 12, "PAQ", "", None),
        ("Limpieza", "Jabón Bolívar barra", "3.20", "2.40", 15, "UND", "", None),
        ("Limpieza", "Lavavajilla Ayudín 360 g", "4.80", "3.60", 3, "UND", "", None),
        ("Cuidado personal", "Pasta dental Colgate 75 ml", "4.50", "3.40", 12, "UND", "", None),
        ("Cuidado personal", "Shampoo Head & Shoulders 375 ml", "18.90", "15.00", 4, "UND", "", None),
        ("Cuidado personal", "Jabón Protex", "3.50", "2.60", 12, "UND", "", None),
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
        ("Jugos y tragos", "Chicha morada", "6.00", "1.50", None, "UND", "", ("Vaso, Jarra 1 L", "", "6, 15")),
        ("Jugos y tragos", "Limonada", "6.00", "1.50", None, "UND", "", ("Vaso, Jarra 1 L", "", "6, 16")),
        ("Jugos y tragos", "Maracuyá", "7.00", "2.00", None, "UND", "", ("Vaso, Jarra 1 L", "", "7, 17")),
        ("Bebidas", "Inca Kola 500 ml", "4.00", "1.80", 36, "UND", "7750182001236", None),
        ("Bebidas", "Coca-Cola 500 ml", "4.00", "1.80", 30, "UND", "7750182002233", None),
        ("Bebidas", "Inca Kola 1.5 L", "9.00", "5.00", 12, "UND", "7750182003230", None),
        ("Bebidas", "Agua San Luis 625 ml", "3.00", "0.90", 24, "UND", "", None),
        ("Bebidas", "Cerveza Cusqueña 620 ml", "12.00", "6.50", 48, "UND", "", None),
        ("Bebidas", "Cerveza Pilsen 630 ml", "10.00", "5.50", 48, "UND", "", None),
        ("Jugos y tragos", "Pisco sour", "18.00", "6.00", None, "UND", "", None),
        ("Jugos y tragos", "Chilcano de pisco", "16.00", "5.00", None, "UND", "", None),
        ("Jugos y tragos", "Café pasado", "5.00", "1.00", None, "UND", "", None),
        ("Jugos y tragos", "Infusión", "3.00", "0.40", None, "UND", "", None),
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
        ("Polos", "Polo oversize estampado", "49.90", "24.00", 2, "UND", "", ("S, M, L, XL", "Negro, Beige")),
        ("Polos", "Polo cuello V", "34.90", "17.00", 2, "UND", "", ("S, M, L", "Blanco, Azul")),
        ("Camisas y blusas", "Camisa manga larga", "79.90", "38.00", 2, "UND", "", ("S, M, L, XL", "")),
        ("Camisas y blusas", "Blusa de lino", "69.90", "32.00", 2, "UND", "", ("S, M, L", "Blanco, Rosado")),
        ("Pantalones", "Jogger cargo", "79.90", "38.00", 2, "UND", "", ("S, M, L", "")),
        ("Pantalones", "Pantalón de vestir", "99.90", "48.00", 1, "UND", "", ("30, 32, 34", "")),
        ("Vestidos y faldas", "Vestido casual", "89.90", "42.00", 2, "UND", "", ("S, M, L", "")),
        ("Vestidos y faldas", "Falda plisada", "59.90", "27.00", 2, "UND", "", ("S, M", "")),
        ("Casacas", "Casaca cortaviento", "119.90", "58.00", 1, "UND", "", ("M, L, XL", "")),
        ("Ropa interior", "Bóxer pack x3", "39.90", "18.00", 6, "PAQ", "", ("S, M, L", "")),
        ("Ropa interior", "Medias tobilleras pack x6", "24.90", "10.00", 10, "PAQ", "", None),
        ("Calzado", "Sandalias", "59.90", "28.00", 2, "PAR", "", ("36, 37, 38, 39", "")),
        ("Calzado", "Botines de cuero", "199.90", "105.00", 1, "PAR", "", ("38, 39, 40, 41", "")),
        ("Accesorios", "Correa de cuero", "45.00", "18.00", 6, "UND", "", None),
        ("Accesorios", "Mochila urbana", "89.90", "42.00", 4, "UND", "", None),
        ("Accesorios", "Lentes de sol", "39.90", "14.00", 8, "UND", "", None),
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
        ("Copias e impresiones", "Anillado", "4.00", None, None, "SRV", "", 10),
        ("Copias e impresiones", "Enmicado A4", "2.00", None, None, "SRV", "", 5),
        ("Copias e impresiones", "Escaneo a PDF", "1.00", None, None, "SRV", "", 3),
        ("Cuadernos", "Cuaderno Justus A5 cuadriculado", "3.50", "2.20", 30, "UND", "", None),
        ("Cuadernos", "Cuaderno anillado A4 100 h", "9.90", "6.80", 15, "UND", "", None),
        ("Cuadernos", "Block cuadriculado A4 x 80", "5.50", "3.80", 20, "UND", "", None),
        ("Lápices y lapiceros", "Resaltador Faber-Castell", "3.00", "1.80", 40, "UND", "", ("", "Amarillo, Verde, Rosado")),
        ("Lápices y lapiceros", "Corrector tipo lapicero", "3.50", "2.20", 15, "UND", "", None),
        ("Lápices y lapiceros", "Portaminas 0.5 mm", "4.50", "2.80", 10, "UND", "", None),
        ("Lápices y lapiceros", "Borrador blanco", "0.80", "0.45", 60, "UND", "", None),
        ("Lápices y lapiceros", "Tajador con depósito", "1.50", "0.90", 30, "UND", "", None),
        ("Papelería", "Folder manila A4", "0.50", "0.25", 200, "UND", "", None),
        ("Papelería", "Sobre manila A4", "0.40", "0.20", 150, "UND", "", None),
        ("Papelería", "Cartulina blanca", "0.80", "0.45", 80, "UND", "", None),
        ("Papelería", "Papel lustre x 10", "1.50", "0.90", 40, "PAQ", "", None),
        ("Arte y manualidades", "Colores Faber-Castell x 12", "9.90", "6.80", 15, "CAJ", "", None),
        ("Arte y manualidades", "Témperas x 7", "8.50", "5.50", 10, "CAJ", "", None),
        ("Arte y manualidades", "Goma en barra 21 g", "3.50", "2.20", 30, "UND", "", None),
        ("Arte y manualidades", "Tijera escolar punta roma", "3.00", "1.80", 20, "UND", "", None),
        ("Mochilas y cartucheras", "Mochila escolar", "79.90", "45.00", 4, "UND", "", ("", "Azul, Rosado, Negro")),
        ("Mochilas y cartucheras", "Cartuchera doble cierre", "15.90", "8.50", 8, "UND", "", None),
        ("Oficina", "Engrapador mediano", "18.00", "11.00", 5, "UND", "", None),
        ("Oficina", "Grapas 26/6 x 5000", "4.50", "2.80", 12, "CAJ", "", None),
        ("Oficina", "Archivador lomo ancho A4", "9.50", "6.50", 10, "UND", "", None),
        ("Oficina", "Calculadora científica", "65.00", "45.00", 3, "UND", "", None),
    ],
    Rubro.PELUQUERIA: [
        ("Cortes", "Corte de cabello", "25.00", None, None, "SRV", "", ("Niño, Adulto", "")),
        ("Cortes", "Corte + barba", "35.00", None, None, "SRV", "", 45),
        ("Coloración", "Tinte completo", "90.00", None, None, "SRV", "", 120),
        ("Uñas", "Manicure", "20.00", None, None, "SRV", "", 40),
        ("Uñas", "Pedicure", "30.00", None, None, "SRV", "", 50),
        ("Productos de venta", "Shampoo profesional 500 ml", "45.00", "28.00", 6, "UND", "", None),
        ("Productos de venta", "Cera para cabello", "25.00", "14.00", 2, "UND", "", None),
        ("Cortes", "Corte de dama", "35.00", None, None, "SRV", "", 45),
        ("Cortes", "Perfilado de barba", "15.00", None, None, "SRV", "", 20),
        ("Peinados", "Lavado y secado", "20.00", None, None, "SRV", "", 30),
        ("Peinados", "Planchado", "30.00", None, None, "SRV", "", 40),
        ("Peinados", "Ondas", "40.00", None, None, "SRV", "", 45),
        ("Peinados", "Peinado de fiesta", "60.00", None, None, "SRV", "", 60),
        ("Coloración", "Retoque de raíz", "60.00", None, None, "SRV", "", 90),
        ("Coloración", "Mechas o reflejos", "120.00", None, None, "SRV", "", 150),
        ("Coloración", "Balayage", "180.00", None, None, "SRV", "", 180),
        ("Tratamientos", "Hidratación capilar", "50.00", None, None, "SRV", "", 45),
        ("Tratamientos", "Keratina", "150.00", None, None, "SRV", "", 150),
        ("Tratamientos", "Limpieza facial", "60.00", None, None, "SRV", "", 60),
        ("Tratamientos", "Depilación de cejas", "12.00", None, None, "SRV", "", 15),
        ("Uñas", "Esmaltado en gel", "40.00", None, None, "SRV", "", 50),
        ("Uñas", "Uñas acrílicas", "80.00", None, None, "SRV", "", 90),
        ("Uñas", "Manicure + pedicure", "45.00", None, None, "SRV", "", 80),
        ("Productos de venta", "Acondicionador profesional 500 ml", "45.00", "28.00", 5, "UND", "", None),
        ("Productos de venta", "Aceite de argán 60 ml", "55.00", "30.00", 4, "UND", "", None),
        ("Productos de venta", "Gel fijador 250 g", "15.00", "8.00", 10, "UND", "", None),
        ("Productos de venta", "Esmalte de uñas", "12.00", "6.00", 20, "UND", "", None),
        ("Productos de venta", "Tratamiento de keratina para casa", "65.00", "38.00", 3, "UND", "", None),
    ],
    Rubro.ACADEMIA: [
        ("Bebidas", "Agua San Luis sin gas 625 ml", "2.00", "0.90", 40, "UND", "", None),
        ("Bebidas", "Bebida rehidratante 500 ml", "3.50", "2.20", 24, "UND", "", None),
        ("Tienda", "Barra de proteína", "6.00", "3.80", 15, "UND", "", None),
        ("Tienda", "Polo deportivo", "35.00", "18.00", 3, "UND", "", ("S, M, L", "")),
        ("Tienda", "Gorro de natación", "15.00", "7.00", 10, "UND", "", None),
        ("Servicios", "Clase suelta", "15.00", None, None, "SRV", "", 60),
        ("Servicios", "Evaluación física", "30.00", None, None, "SRV", "", 30),
        ("Servicios", "Pase diario de gimnasio", "15.00", None, None, "SRV", "", 120),
        ("Servicios", "Clase de natación suelta", "25.00", None, None, "SRV", "", 45),
        ("Servicios", "Clase de baile suelta", "15.00", None, None, "SRV", "", 60),
        ("Servicios", "Entrenamiento personal", "50.00", None, None, "SRV", "", 60),
        ("Servicios", "Alquiler de casillero (mes)", "20.00", None, None, "SRV", "", None),
        ("Bebidas", "Gatorade 500 ml", "4.50", "3.00", 24, "UND", "", None),
        ("Bebidas", "Café americano", "5.00", "1.20", None, "UND", "", None),
        ("Tienda", "Toalla deportiva", "25.00", "12.00", 6, "UND", "", None),
        ("Tienda", "Shaker 600 ml", "20.00", "9.00", 8, "UND", "", None),
        ("Tienda", "Guantes de entrenamiento", "45.00", "22.00", 2, "PAR", "", ("S, M, L", "")),
        ("Tienda", "Lentes de natación", "35.00", "16.00", 6, "UND", "", None),
        ("Tienda", "Proteína whey (porción)", "8.00", "4.50", 40, "UND", "", None),
        ("Tienda", "Candado para casillero", "15.00", "7.00", 10, "UND", "", None),
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
            incluidas = [o for o in ops if o.por_defecto]
            if incluidas and (not azar or azar.random() < .75):  # casi siempre se deja lo que viene con el plato
                ids += [o.pk for o in incluidas[:g.minimo]]
            else:
                ids += [o.pk for o in (azar.sample(ops, g.minimo) if azar else ops[:g.minimo])]
        elif azar and azar.random() < .35:
            ids.append(azar.choice(ops).pk)
    if azar:  # a veces piden sin algo
        ids += [f"s{c.pk}" for c in producto.componentes.all() if c.quitable and not c.cambiar_con_id and azar.random() < .06]
    return ids


def _opciones_restaurante():
    from .models import GrupoOpciones, Opcion
    from .rubros import GRUPOS

    grupos = {}
    for i, (nombre, mn, mx, ops) in enumerate(GRUPOS[Rubro.RESTAURANTE]):
        g = GrupoOpciones.objects.create(nombre=nombre, minimo=mn, maximo=mx, orden=i * 10)
        for j, linea in enumerate(ops):
            n, pr, defecto = leer_linea_opcion(linea)
            Opcion.objects.create(grupo=g, nombre=n, precio=pr, orden=j, por_defecto=defecto)
        grupos[nombre] = g
    frias = ["Inca Kola 500 ml", "Coca-Cola 500 ml", "Inca Kola 1.5 L", "Agua San Luis 625 ml", "Cerveza Cusqueña 620 ml", "Cerveza Pilsen 630 ml"]
    usos = {"Lomo saltado": ["Término de la carne", "Adicionales"], "Bistec a lo pobre": ["Término de la carne", "Adicionales"],
            "Parrilla personal": ["Término de la carne", "Acompañamiento", "Cremas"],
            "Pollo a la brasa": ["Acompañamiento", "Cremas", "Adicionales"], "Combo familiar": ["Cremas"],
            "Alitas BBQ": ["Acompañamiento", "Cremas", "Adicionales"], "Salchipapa": ["Cremas", "Adicionales"],
            "Ceviche": ["Picante"], "Leche de tigre": ["Picante"], "Jalea mixta": ["Picante", "Cremas"],
            "Arroz chaufa": ["Adicionales"], "Tallarines verdes con bistec": ["Adicionales"],
            "Menú ejecutivo": ["Adicionales"], "Menú económico": ["Adicionales"], **{n: ["Temperatura"] for n in frias}}
    for nombre, gs in usos.items():
        p = Producto.objects.filter(nombre=nombre).first()
        if p:
            p.grupos.set([grupos[g] for g in gs])
    # qué lleva cada plato: (nombre, se puede quitar, se cambia con el grupo)
    lleva = {
        "Pollo a la brasa": [("Pollo", False, None), ("Papas fritas", False, "Acompañamiento"), ("Ensalada", True, None)],
        "Alitas BBQ": [("Alitas", False, None), ("Salsa BBQ", True, None), ("Papas fritas", False, "Acompañamiento")],
        "Combo familiar": [("Pollo entero", False, None), ("Papas familiares", True, None), ("Ensalada", True, None)],
        "Parrilla personal": [("Bife", False, None), ("Chorizo", True, None), ("Anticucho", True, None),
                              ("Papas fritas", False, "Acompañamiento"), ("Ensalada", True, None)],
        "Lomo saltado": [("Lomo de res", False, None), ("Cebolla", True, None), ("Tomate", True, None), ("Papas fritas", True, None), ("Arroz", True, None)],
        "Bistec a lo pobre": [("Bistec", False, None), ("Huevo frito", True, None), ("Plátano frito", True, None), ("Papas fritas", True, None),
                              ("Arroz", True, None)],
        "Ceviche": [("Pescado", False, None), ("Cebolla", True, None), ("Camote", True, None), ("Choclo", True, None), ("Cancha", True, None)],
        "Salchipapa": [("Salchicha", False, None), ("Papas fritas", False, None)],
        "Arroz chaufa": [("Arroz", False, None), ("Cebolla china", True, None), ("Tortilla de huevo", True, None)],
        "Causa limeña de pollo": [("Pollo", False, None), ("Palta", True, None), ("Mayonesa", True, None)],
    }
    from .models import Componente

    for nombre, partes in lleva.items():
        p = Producto.objects.filter(nombre=nombre).first()
        if not p:
            continue
        for i, (n, quitable, grupo) in enumerate(partes):
            g = grupos.get(grupo) if grupo else None
            Componente.objects.create(producto=p, nombre=n, quitable=quitable, cambiar_con=g, orden=i)
            if g:
                p.grupos.add(g)
    # menú del día: lo de hoy activo y lo de otros días guardado
    menu = {"Entrada": (["Sopa de casa", "Causa de atún", "Ensalada fresca"], ["Papa rellena", "Crema de zapallo", "Ocopa"]),
            "Segundo": (["Arroz con pollo", "Seco de res con frejoles", "Pescado frito|3", "Tallarines rojos con pollo"],
                        ["Estofado de pollo", "Cau cau", "Lentejas con pescado|2"])}
    diarios = []
    for i, (nombre, (hoy, otros)) in enumerate(menu.items()):
        g = GrupoOpciones.objects.create(nombre=nombre, minimo=1, maximo=1, orden=i, diario=True)
        for j, linea in enumerate(hoy + otros):
            n, _, pr = linea.partition("|")
            Opcion.objects.create(grupo=g, nombre=n, precio=Decimal(pr or "0"), orden=j, activa=linea in hoy)
        diarios.append(g)
    for p in Producto.objects.filter(nombre__startswith="Menú"):
        p.grupos.add(*diarios)


def cargar_catalogo(rubro, usuario=None):
    """Crea el catálogo de ejemplo si todavía no hay productos. Devuelve cuántos productos hay."""
    if Producto.objects.exists():
        return Producto.objects.count()
    for orden, item in enumerate(CATALOGOS.get(rubro, CATALOGOS[Rubro.TIENDA])):
        cat_nombre, nombre, precio, costo, stock, unidad, codigo, extra = item
        cat, _ = Categoria.objects.get_or_create(nombre=cat_nombre, defaults={"orden": orden * 10, "area": area_sugerida(cat_nombre)})
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
        _combo_demo()
    return Producto.objects.count()


def _combo_demo():
    """«Combo familiar» como combo de verdad: pollo entero + ensalada fija y la bebida a elegir (descuenta su stock)."""
    from .models import ComboItem, GrupoOpciones, Opcion

    combo = Producto.objects.filter(nombre="Combo familiar").first()
    pollo = Variante.objects.filter(producto__nombre="Pollo a la brasa", nombre="Entero").first()
    bebidas = [v for v in [Variante.objects.filter(producto__nombre="Inca Kola 1.5 L").first(),
                           Variante.objects.filter(producto__nombre="Chicha morada", nombre="Jarra 1 L").first()] if v]
    if not combo or not pollo:
        return
    combo.tipo, combo.costo = Producto.Tipo.COMBO, None
    combo.descripcion = "Pollo entero con papas, ensalada y cremas, más una bebida para compartir."
    combo.save()
    ComboItem.objects.create(combo=combo, variante=pollo, cantidad=1)
    if len(bebidas) == 2:
        g = GrupoOpciones.objects.create(nombre="Combo familiar: Bebida", minimo=1, maximo=1)
        for i, v in enumerate(bebidas):
            Opcion.objects.create(grupo=g, nombre=v.nombre_completo, variante=v, orden=i, por_defecto=i == 0)
        combo.grupos.add(g)


def marcar_agotados_demo():
    """Lo que se acabó hoy (se llama al final, después de las ventas de ejemplo)."""
    from .models import Opcion
    from .servicios import marcar_agotado

    for p in Producto.objects.filter(nombre="Chupe de camarones"):
        marcar_agotado(p)
    for o in Opcion.objects.filter(nombre="Yuca frita"):
        marcar_agotado(o)
