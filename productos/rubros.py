"""Lo que cambia según el rubro del negocio: categorías sugeridas, nombres de las variantes y valores por defecto."""
from core.models import Rubro

CATEGORIAS = {
    Rubro.TIENDA: ["Abarrotes", "Bebidas", "Lácteos y embutidos", "Snacks y golosinas", "Limpieza", "Cuidado personal"],
    Rubro.RESTAURANTE: ["Entradas", "Marinos", "Platos de fondo", "Pollos y parrillas", "Sopas", "Menú del día", "Bebidas", "Jugos y tragos", "Postres", "Extras"],
    Rubro.ROPA: ["Polos", "Camisas y blusas", "Pantalones", "Vestidos y faldas", "Casacas", "Ropa interior", "Calzado", "Accesorios"],
    Rubro.LIBRERIA: ["Cuadernos", "Lápices y lapiceros", "Papelería", "Arte y manualidades", "Mochilas y cartucheras", "Oficina", "Copias e impresiones"],
    Rubro.PELUQUERIA: ["Cortes", "Peinados", "Coloración", "Tratamientos", "Uñas", "Productos de venta"],
    Rubro.OTRO: ["General"],
}

# (etiqueta opción 1, ejemplo 1, etiqueta opción 2, ejemplo 2)
VARIANTES = {
    Rubro.ROPA: ("Tallas", "S, M, L, XL", "Colores", "Negro, Blanco, Azul"),
    Rubro.RESTAURANTE: ("Tamaños", "Personal, Mediano, Familiar", "Otra opción", ""),
    Rubro.LIBRERIA: ("Presentación", "A4, A5", "Colores", "Azul, Rojo, Negro"),
    Rubro.PELUQUERIA: ("Tipo", "Niño, Adulto", "Largo", "Corto, Largo"),
    Rubro.TIENDA: ("Presentación", "500 ml, 1 L, 3 L", "Sabor", ""),
}
VARIANTES_OTRO = ("Opción 1", "Grande, Pequeño", "Opción 2", "")


def rubro_actual():
    from core.models import Ajustes

    return Ajustes.cargar().rubro


def etiquetas_variantes(rubro=None):
    return VARIANTES.get(rubro or rubro_actual(), VARIANTES_OTRO)


def valores_iniciales(rubro=None):
    """Valores por defecto de un producto nuevo según el rubro."""
    rubro = rubro or rubro_actual()
    if rubro == Rubro.PELUQUERIA:
        return {"tipo": "S", "maneja_stock": False}
    if rubro == Rubro.RESTAURANTE:
        return {"maneja_stock": False}
    return {}


# Grupos de opciones sugeridos: (nombre, mínimo, máximo, ["Opción" o "Opción|precio"])
GRUPOS = {
    Rubro.RESTAURANTE: [
        ("Término de la carne", 1, 1, ["Inglés", "Término medio", "Tres cuartos", "Bien cocido"]),
        ("Acompañamiento", 1, 1, ["Papas fritas *", "Arroz", "Ensalada", "Yuca frita"]),
        ("Adicionales", 0, 0, ["Huevo frito|2", "Queso|3", "Porción de papas|5", "Porción de arroz|3"]),
        ("Cremas", 0, 0, ["Mayonesa", "Ketchup", "Mostaza", "Ají", "Huancaína", "Tártara"]),
        ("Temperatura", 0, 1, ["Helada", "Al tiempo"]),
        ("Picante", 1, 1, ["Normal *", "Sin ají", "Bien picante"]),
    ],
    Rubro.PELUQUERIA: [
        ("Adicionales", 0, 0, ["Lavado|5", "Peinado|10", "Tratamiento hidratante|20"]),
    ],
    Rubro.TIENDA: [
        ("Temperatura", 0, 1, ["Helada", "Al tiempo"]),
    ],
}
