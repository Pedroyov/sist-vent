import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.utils import TamanoMaximo
from django.db.models import F, Q
from django.utils import timezone

from alumnos.models import Alumno
from core.models import AnioLectivo

CERO = Decimal("0.00")
MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


MENSAJE_RECORDATORIO = (
    "Estimado(a) {apoderado}, le saludamos de {colegio}. "
    "Le recordamos que {alumno} tiene pendiente:\n{detalle}\n"
    "*Total vencido: S/ {total}*\n"
    "Si ya realizó el pago, por favor ignore este mensaje. ¡Gracias!"
)


def dinero(valor):
    return Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def MontoField(verbose_name=None, **kwargs):
    kwargs.setdefault("max_digits", 10)
    kwargs.setdefault("decimal_places", 2)
    kwargs.setdefault("default", CERO)
    kwargs.setdefault("validators", [MinValueValidator(CERO)])
    return models.DecimalField(verbose_name, **kwargs)


class ConfigCobranza(models.Model):
    """Reglas de cobro de un año lectivo."""

    class TipoMora(models.TextChoices):
        FIJA = "FIJA", "Monto fijo por cuota vencida"
        DIARIA = "DIA", "Monto por cada día de atraso"

    anio_lectivo = models.OneToOneField(AnioLectivo, on_delete=models.CASCADE, related_name="config_cobranza")
    monto_matricula = MontoField("monto de matrícula")
    monto_pension = MontoField("monto de pensión mensual")
    mes_inicio = models.PositiveSmallIntegerField(
        "primera pensión", choices=[(i, MESES[i]) for i in range(1, 13)], default=3
    )
    mes_fin = models.PositiveSmallIntegerField(
        "última pensión", choices=[(i, MESES[i]) for i in range(1, 13)], default=12
    )
    dia_vencimiento = models.PositiveSmallIntegerField(
        "día de vencimiento",
        default=31,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Día del mes en que vence cada pensión. 31 = último día del mes.",
    )
    mora_activa = models.BooleanField("cobrar mora", default=False)
    mora_tipo = models.CharField("tipo de mora", max_length=4, choices=TipoMora.choices, default=TipoMora.FIJA)
    mora_monto = MontoField("monto de mora")
    mora_dias_gracia = models.PositiveSmallIntegerField(
        "días de tolerancia", default=0, help_text="Días después del vencimiento antes de cobrar mora."
    )
    mensaje_recordatorio = models.TextField(
        "mensaje de recordatorio",
        default=MENSAJE_RECORDATORIO,
        help_text="Puedes usar: {apoderado}, {alumno}, {detalle}, {total}, {colegio}",
    )

    class Meta:
        verbose_name = "configuración de cobranza"
        verbose_name_plural = "configuraciones de cobranza"

    def __str__(self):
        return f"Cobranza {self.anio_lectivo}"

    def vencimiento_de(self, mes):
        anio = self.anio_lectivo.anio
        ultimo = calendar.monthrange(anio, mes)[1]
        return date(anio, mes, min(self.dia_vencimiento, ultimo))

    @property
    def meses(self):
        return list(range(self.mes_inicio, self.mes_fin + 1))


class Concepto(models.Model):
    """Algo que se cobra: la matrícula, cada pensión mensual u otro cobro."""

    class Tipo(models.TextChoices):
        MATRICULA = "MAT", "Matrícula"
        PENSION = "PEN", "Pensión"
        OTRO = "OTR", "Otro"

    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="conceptos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    nombre = models.CharField(max_length=100)
    mes = models.PositiveSmallIntegerField(null=True, blank=True)
    monto = MontoField()
    vencimiento = models.DateField()
    automatico = models.BooleanField(
        default=False, help_text="Se asigna solo a cada alumno matriculado (matrícula y pensiones)."
    )

    class Meta:
        verbose_name = "concepto de cobro"
        verbose_name_plural = "conceptos de cobro"
        ordering = ["anio_lectivo", "vencimiento", "tipo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["anio_lectivo", "mes"], condition=Q(tipo="PEN"), name="una_pension_por_mes"
            ),
            models.UniqueConstraint(
                fields=["anio_lectivo"], condition=Q(tipo="MAT"), name="una_matricula_por_anio_cobro"
            ),
        ]

    def __str__(self):
        return self.nombre


class Descuento(models.Model):
    class Tipo(models.TextChoices):
        PORCENTAJE = "POR", "Porcentaje (%)"
        MONTO = "MON", "Monto fijo (S/)"

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="descuentos")
    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="descuentos")
    motivo = models.CharField(max_length=100, help_text='Ej.: "Hermanos", "Media beca", "Hijo de docente"')
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.PORCENTAJE)
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(CERO)])
    en_pensiones = models.BooleanField("aplica a pensiones", default=True)
    en_matricula = models.BooleanField("aplica a matrícula", default=False)

    class Meta:
        verbose_name = "descuento"
        verbose_name_plural = "descuentos"

    def __str__(self):
        return f"{self.motivo} ({self.texto_valor})"

    @property
    def texto_valor(self):
        return f"{self.valor:g}%" if self.tipo == self.Tipo.PORCENTAJE else f"S/ {self.valor}"

    def aplica_a(self, concepto):
        return (concepto.tipo == Concepto.Tipo.PENSION and self.en_pensiones) or (
            concepto.tipo == Concepto.Tipo.MATRICULA and self.en_matricula
        )

    def calcular(self, monto):
        if self.tipo == self.Tipo.PORCENTAJE:
            return dinero(monto * min(self.valor, Decimal(100)) / 100)
        return min(dinero(self.valor), monto)


class CargoQuerySet(models.QuerySet):
    def vigentes(self):
        return self.filter(anulado=False)

    def pendientes(self):
        return self.vigentes().filter(pagado__lt=F("monto") - F("descuento"))

    def vencidos(self, hoy=None):
        return self.pendientes().filter(vencimiento__lt=hoy or timezone.localdate())


class Cargo(models.Model):
    """Lo que un alumno debe por un concepto (su deuda)."""

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="cargos")
    concepto = models.ForeignKey(Concepto, on_delete=models.PROTECT, related_name="cargos")
    monto = MontoField()
    descuento = MontoField()
    pagado = MontoField(help_text="Se actualiza al registrar o anular pagos.")
    vencimiento = models.DateField()
    anulado = models.BooleanField(default=False, help_text="Ya no se cobra (por ejemplo, el alumno se retiró).")

    objects = CargoQuerySet.as_manager()

    class Meta:
        verbose_name = "cargo"
        verbose_name_plural = "cargos"
        ordering = ["vencimiento", "concepto__tipo", "id"]
        constraints = [
            models.UniqueConstraint(fields=["alumno", "concepto"], name="un_cargo_por_concepto"),
        ]

    def __str__(self):
        return f"{self.concepto} – {self.alumno}"

    @property
    def total(self):
        return self.monto - self.descuento

    @property
    def saldo(self):
        return max(self.total - self.pagado, CERO)

    @property
    def cancelado(self):
        return self.saldo == CERO

    @property
    def vencido(self):
        return not self.cancelado and self.vencimiento < timezone.localdate()

    def mora(self, config, hoy=None):
        """Mora a la fecha (no se guarda; se cobra en el pago)."""
        if not config or not config.mora_activa or self.cancelado or self.anulado:
            return CERO
        hoy = hoy or timezone.localdate()
        dias = (hoy - self.vencimiento).days - config.mora_dias_gracia
        if dias <= 0:
            return CERO
        if config.mora_tipo == ConfigCobranza.TipoMora.DIARIA:
            return dinero(config.mora_monto * dias)
        return dinero(config.mora_monto)


class Pago(models.Model):
    class Metodo(models.TextChoices):
        EFECTIVO = "EFE", "Efectivo"
        YAPE = "YAP", "Yape"
        PLIN = "PLI", "Plin"
        TRANSFERENCIA = "TRA", "Transferencia"
        DEPOSITO = "DEP", "Depósito"
        TARJETA = "TAR", "Tarjeta"

    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.PROTECT, related_name="pagos")
    numero = models.PositiveIntegerField("N° de recibo")
    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name="pagos")
    fecha = models.DateField(default=timezone.localdate)
    metodo = models.CharField("método de pago", max_length=3, choices=Metodo.choices, default=Metodo.EFECTIVO)
    numero_operacion = models.CharField("N° de operación", max_length=40, blank=True)
    voucher = models.ImageField("foto del voucher", upload_to="cobranza/vouchers/%Y/%m/", blank=True, validators=[TamanoMaximo(5)])
    total = MontoField()
    observacion = models.CharField("observación", max_length=200, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pagos_registrados")
    registrado_en = models.DateTimeField(auto_now_add=True)
    anulado = models.BooleanField(default=False)
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="pagos_anulados"
    )
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField("motivo de anulación", max_length=200, blank=True)

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-fecha", "-numero"]
        constraints = [
            models.UniqueConstraint(fields=["anio_lectivo", "numero"], name="recibo_unico_por_anio"),
        ]

    def __str__(self):
        return f"Recibo {self.numero_texto}"

    @property
    def numero_texto(self):
        return f"{self.anio_lectivo.anio}-{self.numero:06d}"


class PagoDetalle(models.Model):
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name="detalles")
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT, related_name="pagos")
    monto = MontoField(help_text="Parte aplicada a la deuda")
    mora = MontoField()

    class Meta:
        verbose_name = "detalle de pago"
        verbose_name_plural = "detalles de pago"

    @property
    def subtotal(self):
        return self.monto + self.mora


class Recordatorio(models.Model):
    """Registro de cada aviso de deuda enviado (por ahora, por WhatsApp)."""

    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name="recordatorios")
    anio_lectivo = models.ForeignKey(AnioLectivo, on_delete=models.CASCADE, related_name="recordatorios")
    fecha = models.DateTimeField(auto_now_add=True)
    monto = MontoField("monto vencido al avisar")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recordatorios")

    class Meta:
        verbose_name = "recordatorio"
        verbose_name_plural = "recordatorios"
        ordering = ["-fecha"]
