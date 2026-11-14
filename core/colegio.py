"""Acceso rápido a los datos del colegio (Configuración → Datos del colegio)."""


def datos():
    from .models import Ajustes

    return Ajustes.cargar()


def nombre():
    return datos().nombre_mostrar
