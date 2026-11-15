"""Conectores con quien envía a SUNAT. Todos reciben el comprobante ya armado y devuelven un Resultado.

Agregar otro proveedor = otra clase con `emitir` y `consultar`, y su opción en Config.Proveedor.
"""
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TIMEOUT = 20


@dataclass
class Resultado:
    estado: str  # "ACE" aceptado, "ENV" enviado (SUNAT aún no responde), "REC" rechazado, "PEN" no se pudo enviar (reintentar)
    mensaje: str = ""
    enlace_pdf: str = ""
    enlace_xml: str = ""
    hash: str = ""
    qr: str = ""
    crudo: dict = field(default_factory=dict)


class ErrorConexion(Exception):
    """No hubo respuesta (sin internet, proveedor caído): el comprobante queda pendiente y se reintenta."""


def texto_qr(c, ruc, hash_=""):
    """Formato de SUNAT: RUC | tipo | serie | número | IGV | total | fecha | tipo doc. cliente | doc. cliente | hash |"""
    return "|".join([ruc, c.tipo, c.serie, str(c.numero), f"{c.igv:.2f}", f"{c.total:.2f}", c.fecha.strftime("%Y-%m-%d"),
                     c.cliente_tipo_doc if c.cliente_tipo_doc != "-" else "0", c.cliente_doc or "", hash_]) + "|"


class Prueba:
    """Simula a SUNAT: acepta todo al instante. Sirve para probar el sistema; los comprobantes no tienen valor."""

    def __init__(self, config, ruc):
        self.ruc = ruc

    def emitir(self, c):
        h = hashlib.sha1(f"{self.ruc}{c.numero_str}{c.total}".encode()).hexdigest()[:28]
        return Resultado("ACE", "Aceptado (modo prueba: no se envió a SUNAT).", hash=h, qr=texto_qr(c, self.ruc, h))

    def consultar(self, c):
        return self.emitir(c)


class Nubefact:
    """API JSON de Nubefact (PSE/OSE). Ruta y token se sacan de su panel: API - Integración."""

    TIPOS = {"01": 1, "03": 2, "07": 3}
    IGV = {"G": 1, "E": 8, "I": 9}

    def __init__(self, config, ruc):
        self.ruta, self.token, self.config, self.ruc = config.ruta, config.token, config, ruc

    def _post(self, datos):
        req = urllib.request.Request(self.ruta, data=json.dumps(datos).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f'Token token="{self.token}"'})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:  # Nubefact responde los errores de validación con código 4xx y un JSON
            try:
                return json.loads(e.read().decode() or "{}")
            except ValueError:
                raise ErrorConexion(f"El proveedor respondió con error {e.code}.")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorConexion(f"No se pudo conectar con el proveedor: {getattr(e, 'reason', e)}")
        except ValueError:
            raise ErrorConexion("El proveedor respondió algo que no se entiende.")

    def _resultado(self, r, c):
        if r.get("errors"):
            msg = str(r.get("errors"))[:480]
            return Resultado("REC", msg, crudo=r), str(r.get("codigo", ""))
        acepta = r.get("aceptada_por_sunat")
        estado = "ACE" if acepta else "ENV"
        msg = r.get("sunat_description") or ("Aceptado por SUNAT." if acepta else "Enviado: SUNAT confirma en unos minutos.")
        if r.get("sunat_soap_error"):
            estado, msg = "REC", str(r["sunat_soap_error"])[:480]
        return Resultado(estado, msg, r.get("enlace_del_pdf", ""), r.get("enlace_del_xml", ""), r.get("codigo_hash", ""),
                         r.get("cadena_para_codigo_qr", "") or texto_qr(c, self.ruc, r.get("codigo_hash", "")), r), ""

    def emitir(self, c):
        res, codigo = self._resultado(self._post(self.armar(c)), c)
        if res.estado == "REC" and (codigo == "23" or "existe" in res.mensaje.lower()):
            return self.consultar(c)  # ya se había enviado (por ejemplo, se cortó la respuesta): se pregunta cómo quedó
        return res

    def consultar(self, c):
        res, _ = self._resultado(self._post({"operacion": "consultar_comprobante", "tipo_de_comprobante": self.TIPOS[c.tipo],
                                             "serie": c.serie, "numero": c.numero}), c)
        return res

    def armar(self, c):
        d = {
            "operacion": "generar_comprobante", "tipo_de_comprobante": self.TIPOS[c.tipo], "serie": c.serie, "numero": c.numero,
            "sunat_transaction": 1, "cliente_tipo_de_documento": c.cliente_tipo_doc, "cliente_numero_de_documento": c.cliente_doc or "-",
            "cliente_denominacion": c.cliente_nombre or "CLIENTES VARIOS", "cliente_direccion": c.cliente_direccion, "cliente_email": "",
            "fecha_de_emision": c.fecha.strftime("%d-%m-%Y"), "moneda": 1, "porcentaje_de_igv": f"{c.igv_pct:.2f}",
            "total_gravada": f"{c.gravada:.2f}" if c.gravada else "", "total_exonerada": f"{c.exonerada:.2f}" if c.exonerada else "",
            "total_inafecta": f"{c.inafecta:.2f}" if c.inafecta else "", "total_igv": f"{c.igv:.2f}", "total": f"{c.total:.2f}",
            "detraccion": False, "enviar_automaticamente_a_la_sunat": True, "enviar_automaticamente_al_cliente": False,
            "formato_de_pdf": "TICKET",
            "items": [{"unidad_de_medida": i["unidad"], "codigo": i.get("codigo", ""), "descripcion": i["descripcion"],
                       "cantidad": i["cantidad"], "valor_unitario": i["valor_unitario"], "precio_unitario": i["precio_unitario"],
                       "descuento": "", "subtotal": i["subtotal"], "tipo_de_igv": self.IGV[i["afectacion"]], "igv": i["igv"],
                       "total": i["total"], "anticipo_regularizacion": False} for i in c.detalle],
        }
        if c.es_nota:
            d.update({"documento_que_se_modifica_tipo": self.TIPOS[c.modifica.tipo], "documento_que_se_modifica_serie": c.modifica.serie,
                      "documento_que_se_modifica_numero": c.modifica.numero, "tipo_de_nota_de_credito": 1, "observaciones": c.motivo})
        return d


def conector(config, ruc):
    from .models import Config

    return {Config.Proveedor.PRUEBA: Prueba, Config.Proveedor.NUBEFACT: Nubefact}[config.proveedor](config, ruc)
