"""Validación de documentos peruanos (sin consultar a RENIEC ni SUNAT)."""
import re

PESOS_RUC = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def ruc_valido(ruc):
    """11 dígitos, empieza en 10, 15, 16, 17 o 20 y cumple el dígito verificador (módulo 11)."""
    if not re.fullmatch(r"\d{11}", ruc or "") or ruc[:2] not in ("10", "15", "16", "17", "20"):
        return False
    suma = sum(int(d) * p for d, p in zip(ruc[:10], PESOS_RUC))
    resto = 11 - suma % 11
    verificador = 0 if resto == 10 else 1 if resto == 11 else resto
    return verificador == int(ruc[10])


def validar(tipo, numero):
    """Devuelve (numero_limpio, mensaje_de_error_o_None)."""
    numero = re.sub(r"[\s.-]", "", str(numero or "")).upper()
    if tipo == "SD":
        return "", None
    if not numero:
        return "", "Escribe el número de documento (o elige «Sin documento»)."
    if tipo == "DNI" and not re.fullmatch(r"\d{8}", numero):
        return numero, "El DNI tiene 8 dígitos."
    if tipo == "RUC" and not ruc_valido(numero):
        return numero, "Ese RUC no es válido (revisa los 11 dígitos)."
    if tipo == "CE" and not re.fullmatch(r"[A-Z0-9]{8,12}", numero):
        return numero, "El carné de extranjería tiene entre 8 y 12 caracteres."
    if tipo == "PAS" and not re.fullmatch(r"[A-Z0-9]{5,12}", numero):
        return numero, "Pasaporte no válido."
    return numero, None


def adivinar_tipo(numero):
    """Para lo que se escribe al vuelo en el cobro: 8 dígitos = DNI, 11 = RUC."""
    numero = re.sub(r"\D", "", str(numero or ""))
    return {8: "DNI", 11: "RUC"}.get(len(numero))
