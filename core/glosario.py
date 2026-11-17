"""Palabras que cambian según el tipo de negocio (menú, títulos y botones).

En plantillas: {{ T.productos }}. En Python: palabras(ajustes)["productos"].
Para un rubro nuevo basta con agregar sus palabras aquí; lo que no se indique usa la palabra general.
"""
from .models import Rubro

GENERAL = {
    "productos": "Productos",          # menú y título del catálogo
    "vender": "Vender",                # pantalla de venta en mostrador
    "cobranzas": "Cobranzas",          # módulo de mensualidades
    "inscritos": "Inscritos",          # quienes pagan un plan
    "inscribir": "Inscribir",
    "planes": "Planes",
}

POR_RUBRO = {
    Rubro.RESTAURANTE: {"productos": "Carta", "vender": "Venta rápida"},
    Rubro.PELUQUERIA: {"productos": "Servicios y productos", "vender": "Cobrar", "cobranzas": "Paquetes",
                       "inscritos": "Con paquete", "inscribir": "Vender paquete", "planes": "Paquetes"},
    Rubro.ACADEMIA: {"cobranzas": "Mensualidades", "inscritos": "Alumnos y socios"},
}


def palabras(ajustes):
    return {**GENERAL, **POR_RUBRO.get(ajustes.rubro, {})}
