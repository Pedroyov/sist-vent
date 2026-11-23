"""Chequeo de salud para el hosting (DigitalOcean App Platform) y los avisos de caída.

GET /salud/ → «ok» (200) si el sistema responde y la base de datos contesta; si no, 503. Va primero en MIDDLEWARE:
no pasa por el dominio permitido, la redirección a https ni el ingreso (el chequeo del hosting llega por dentro).
No muestra ningún dato del negocio.
"""
from django.db import connection
from django.http import HttpResponse


class SaludMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != "/salud/":
            return self.get_response(request)
        try:
            with connection.cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
        except Exception:  # noqa: BLE001 — cualquier falla de la base es «no está sano»
            return HttpResponse("base de datos sin respuesta", status=503, content_type="text/plain")
        resp = HttpResponse("ok", content_type="text/plain")
        resp["Cache-Control"] = "no-store"
        return resp
