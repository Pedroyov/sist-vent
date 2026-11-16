import re

from django import forms

from .models import Config

SERIE = re.compile(r"^[A-Z0-9]{4}$")


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["proveedor", "ruta", "token", "igv", "afectacion", "por_defecto", "serie_boleta", "serie_factura", "serie_nc_boleta",
                  "serie_nc_factura", "credito_activo", "credito_dias"]
        widgets = {"token": forms.PasswordInput(render_value=True, attrs={"autocomplete": "new-password"}),
                   "proveedor": forms.RadioSelect, "por_defecto": forms.RadioSelect}

    def _serie(self, campo, letra):
        v = self.cleaned_data[campo].strip().upper()
        if not SERIE.match(v) or not v.startswith(letra):
            raise forms.ValidationError(f"4 letras o números y empieza con {letra} (ej.: {letra}001).")
        return v

    def clean_serie_boleta(self):
        return self._serie("serie_boleta", "B")

    def clean_serie_factura(self):
        return self._serie("serie_factura", "F")

    def clean_serie_nc_boleta(self):
        return self._serie("serie_nc_boleta", "B")

    def clean_serie_nc_factura(self):
        return self._serie("serie_nc_factura", "F")

    def clean(self):
        d = super().clean()
        if d.get("proveedor") == Config.Proveedor.NUBEFACT and not (d.get("ruta") and d.get("token")):
            self.add_error("ruta", "Para Nubefact escribe la ruta y el token de su panel (API - Integración).")
        series = [d.get(c) for c in ("serie_boleta", "serie_factura", "serie_nc_boleta", "serie_nc_factura") if d.get(c)]
        if len(series) != len(set(series)):
            self.add_error("serie_nc_boleta", "Cada serie tiene que ser distinta.")
        return d
