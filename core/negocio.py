"""Acceso rápido a los datos del negocio (Configuración → Datos del negocio)."""


def datos():
    from .models import Ajustes

    return Ajustes.cargar()


def nombre():
    return datos().nombre_mostrar
