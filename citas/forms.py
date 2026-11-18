from django import forms

from .models import DIAS, Ausencia, Config


class HorarioDiaForm(forms.Form):
    """Una fila por día de la semana en la pantalla del profesional."""

    trabaja = forms.BooleanField(required=False)
    entrada = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    salida = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    descanso_desde = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    descanso_hasta = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    def clean(self):
        d = super().clean()
        if d.get("trabaja"):
            if not d.get("entrada") or not d.get("salida"):
                raise forms.ValidationError("Pon la hora de entrada y de salida.")
            if d["salida"] <= d["entrada"]:
                raise forms.ValidationError("La salida debe ser después de la entrada.")
            dd, dh = d.get("descanso_desde"), d.get("descanso_hasta")
            if bool(dd) != bool(dh):
                raise forms.ValidationError("Pon el inicio y el fin del refrigerio (o deja los dos vacíos).")
            if dd and not (d["entrada"] <= dd < dh <= d["salida"]):
                raise forms.ValidationError("El refrigerio debe estar dentro del horario.")
        return d


HorariosFormSet = forms.formset_factory(HorarioDiaForm, extra=0, min_num=7, max_num=7)


class AusenciaForm(forms.ModelForm):
    class Meta:
        model = Ausencia
        fields = ["desde", "hasta", "hora_desde", "hora_hasta", "motivo"]
        widgets = {"desde": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "hasta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "hora_desde": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "hora_hasta": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "motivo": forms.TextInput(attrs={"list": "motivos", "placeholder": "Vacaciones, día libre, permiso…"})}
        labels = {"hora_desde": "Solo desde (hora)", "hora_hasta": "hasta (hora)"}

    def clean(self):
        d = super().clean()
        if d.get("desde") and d.get("hasta") and d["hasta"] < d["desde"]:
            raise forms.ValidationError("La fecha «hasta» es antes que «desde».")
        hd, hh = d.get("hora_desde"), d.get("hora_hasta")
        if bool(hd) != bool(hh):
            raise forms.ValidationError("Para una ausencia de unas horas, pon las dos horas (o ninguna para todo el día).")
        if hd and hh <= hd:
            raise forms.ValidationError("La hora final debe ser después de la inicial.")
        return d


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["intervalo", "duracion", "dias_compartir"]


__all__ = ["DIAS", "HorariosFormSet", "AusenciaForm", "ConfigForm"]
