"""Cobranzas: mensualidades y cuotas de academias, gimnasios, talleres y similares.

Un **plan** (precio y cada cuánto se paga) → una **inscripción** de un cliente a ese plan → sus **cuotas**
(se generan solas) → los **pagos** que las cubren (entran a la caja como cualquier cobro).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

CERO = Decimal("0")


class Config(models.Model):
    """Opciones de cobranza (una sola fila). Todo empieza apagado: lo básico funciona sin tocar nada."""

    mora_activa = models.BooleanField("cobrar mora por atraso", default=False,
                                      help_text="Un monto fijo que se suma a la cuota cuando pasa su fecha (y los días de gracia).")
    mora_monto = models.DecimalField("monto de la mora", max_digits=8, decimal_places=2, default=CERO,
                                     validators=[MinValueValidator(CERO)])
    dias_gracia = models.PositiveSmallIntegerField("días de gracia", default=0, validators=[MaxValueValidator(60)],
                                                   help_text="Días después del vencimiento en que todavía no se cobra mora.")
    dias_aviso = models.PositiveSmallIntegerField("avisar antes del vencimiento", default=3, validators=[MaxValueValidator(30)],
                                                  help_text="Días antes de que venza una cuota para que salga en «Por vencer».")
    # --- Gimnasios: control de ingreso y congelar (función «Control de ingreso» en Datos del negocio) ---
    dias_tolerancia = models.PositiveSmallIntegerField(
        "días de tolerancia al entrar", default=0, validators=[MaxValueValidator(15)],
        help_text="Días que el socio puede seguir entrando después de que vence su pago (sale en amarillo). 0 = ninguno.")
    congelar_dias = models.PositiveSmallIntegerField(
        "días para congelar al año", default=0, validators=[MaxValueValidator(180)],
        help_text="Cuántos días al año puede congelar cada socio su membresía (viaje, lesión): su vencimiento se corre esos días. "
                  "0 = no se congela.")

    class Meta:
        verbose_name = "configuración de cobranzas"
        verbose_name_plural = "configuración de cobranzas"

    def __str__(self):
        return "Configuración de cobranzas"

    @classmethod
    def cargar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def cobra_mora(self):
        return self.mora_activa and self.mora_monto > 0


class Plan(models.Model):
    class Frecuencia(models.TextChoices):
        MENSUAL = "MEN", "Mensual"
        QUINCENAL = "QUI", "Quincenal"
        SEMANAL = "SEM", "Semanal"
        TRIMESTRAL = "TRI", "Trimestral"
        SEMESTRAL = "SES", "Semestral"
        ANUAL = "ANU", "Anual"
        UNICO = "UNI", "Pago único"

    nombre = models.CharField(max_length=80, help_text="Ej.: «Gimnasio mensual», «Inglés básico», «Vacaciones útiles».")
    precio = models.DecimalField("precio de cada cuota", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    frecuencia = models.CharField("cada cuánto paga", max_length=3, choices=Frecuencia.choices, default=Frecuencia.MENSUAL)
    num_cuotas = models.PositiveSmallIntegerField(
        "número de cuotas", default=0, validators=[MaxValueValidator(60)],
        help_text="Para cursos con duración fija (ej.: 6). 0 = sigue cobrando hasta que se dé de baja.")
    matricula = models.DecimalField("matrícula o inscripción", max_digits=10, decimal_places=2, default=CERO,
                                    validators=[MinValueValidator(CERO)], help_text="Se cobra una sola vez al inscribirse. 0 = no tiene.")
    duracion_dias = models.PositiveSmallIntegerField(
        "días de vigencia", default=0, validators=[MaxValueValidator(366)],
        help_text="Solo para pago único: cuántos días sirve desde que empieza (pase diario = 1, promoción de verano = 60). 0 = no vence.")
    clases = models.PositiveSmallIntegerField(
        "clases o ingresos por periodo", default=0, validators=[MaxValueValidator(999)],
        help_text="Con Control de ingreso: cuántas veces puede entrar en cada periodo pagado (12 clases al mes, paquete de 10). "
                  "0 = sin límite.")
    descripcion = models.CharField("descripción", max_length=200, blank=True, help_text="Horario, sede o lo que incluye.")
    activo = models.BooleanField(default=True, help_text="Si lo desactivas, ya no se puede inscribir a nadie nuevo (los inscritos siguen).")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "plan"
        verbose_name_plural = "planes"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    @property
    def resumen(self):
        if self.frecuencia == self.Frecuencia.UNICO:
            texto = f"S/ {self.precio:.2f} (pago único" + (f", {self.duracion_dias} día{'s' if self.duracion_dias != 1 else ''}" if self.duracion_dias else "") + ")"
        else:
            texto = f"S/ {self.precio:.2f} {self.get_frecuencia_display().lower()}"
            if self.num_cuotas:
                texto += f" × {self.num_cuotas}"
        if self.clases:
            texto += f" · {self.clases} clase{'s' if self.clases != 1 else ''}"
        return texto

    @property
    def es_indefinido(self):
        return self.frecuencia != self.Frecuencia.UNICO and not self.num_cuotas


class Inscripcion(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACT", "Activa"
        TERMINADA = "TER", "Terminada"
        BAJA = "BAJ", "De baja"

    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="inscripciones",
                                help_text="Quien paga.")
    alumno = models.CharField("alumno o socio", max_length=120, blank=True,
                              help_text="Si no es el mismo que paga (ej.: el hijo). Vacío = el mismo cliente.")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="inscripciones")
    precio = models.DecimalField("precio de cada cuota", max_digits=10, decimal_places=2,
                                 validators=[MinValueValidator(CERO)], help_text="El del plan, o menos si tiene descuento o beca.")
    inicio = models.DateField("empieza el", default=timezone.localdate)
    dia_pago = models.PositiveSmallIntegerField("día de pago", validators=[MinValueValidator(1), MaxValueValidator(31)],
                                                help_text="Para planes mensuales: el día del mes en que vence cada cuota.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ACTIVA)
    fin = models.DateField("terminó el", null=True, blank=True)
    motivo_baja = models.CharField(max_length=200, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "inscripción"
        verbose_name_plural = "inscripciones"
        ordering = ["-inicio", "-id"]

    def __str__(self):
        return f"{self.quien} · {self.plan}"

    @property
    def quien(self):
        return self.alumno or self.cliente.nombre

    @property
    def activa(self):
        return self.estado == self.Estado.ACTIVA


class Cuota(models.Model):
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name="cuotas")
    numero = models.PositiveSmallIntegerField(help_text="0 = matrícula.")
    concepto = models.CharField(max_length=80)
    vence = models.DateField()
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    mora = models.DecimalField(max_digits=8, decimal_places=2, default=CERO)
    mora_perdonada = models.BooleanField(default=False)
    pagado = models.DecimalField(max_digits=10, decimal_places=2, default=CERO)
    anulada = models.BooleanField("exonerada", default=False)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "cuota"
        verbose_name_plural = "cuotas"
        ordering = ["vence", "numero"]
        constraints = [models.UniqueConstraint(fields=["inscripcion", "numero"], name="cuota_unica_por_inscripcion")]

    def __str__(self):
        return f"{self.concepto} · {self.inscripcion.quien}"

    @property
    def total(self):
        return self.monto + self.mora

    @property
    def pendiente(self):
        if self.anulada:
            return CERO
        return max(CERO, self.total - self.pagado)

    @property
    def pagada(self):
        return not self.anulada and self.pendiente == 0

    def vencida(self, hoy=None):
        return self.pendiente > 0 and self.vence < (hoy or timezone.localdate())

    def dias_atraso(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return (hoy - self.vence).days if self.vencida(hoy) else 0

    @property
    def estado(self):
        if self.anulada:
            return "exonerada"
        if self.pagada:
            return "pagada"
        if self.vencida():
            return "vencida"
        if self.pagado:
            return "parcial"
        return "pendiente"


class Pago(models.Model):
    """Lo que paga un cliente en una vez; puede cubrir varias cuotas (o parte de una)."""

    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="pagos_cobranza")
    fecha = models.DateTimeField(default=timezone.now)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    metodo = models.CharField("método", max_length=3)
    referencia = models.CharField(max_length=60, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    sesion_caja = models.ForeignKey("caja.SesionCaja", on_delete=models.PROTECT, null=True, blank=True, related_name="pagos_cobranza")
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    motivo_anulacion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "pago de cuotas"
        verbose_name_plural = "pagos de cuotas"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["fecha"])]

    def __str__(self):
        return f"Recibo {self.numero} · {self.cliente}"

    @property
    def numero(self):
        return f"R-{self.pk:06d}"

    def get_metodo_display(self):
        from ventas.models import MetodoPago

        return dict(MetodoPago.choices).get(self.metodo, self.metodo)


class PagoCuota(models.Model):
    """Cuánto de un pago se aplicó a cada cuota."""

    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name="detalles")
    cuota = models.ForeignKey(Cuota, on_delete=models.PROTECT, related_name="aplicaciones")
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "cuota pagada"
        verbose_name_plural = "cuotas pagadas"


class Congelamiento(models.Model):
    """El socio pausa su membresía (viaje, lesión): esos días no entra y su vencimiento se corre. Nada se borra: si vuelve
    antes, se acorta."""

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name="congelamientos")
    desde = models.DateField()
    hasta = models.DateField()
    motivo = models.CharField(max_length=200)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "congelamiento"
        verbose_name_plural = "congelamientos"
        ordering = ["-desde"]

    def __str__(self):
        return f"{self.inscripcion.quien}: {self.desde:%d/%m} al {self.hasta:%d/%m}"

    @property
    def dias(self):
        return (self.hasta - self.desde).days + 1


class Asistencia(models.Model):
    """Cada vez que el socio entra (control de ingreso). `con_permiso`: entró sin estar al día porque alguien lo dejó pasar."""

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name="asistencias")
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    con_permiso = models.BooleanField("entró sin estar al día", default=False)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "ingreso"
        verbose_name_plural = "ingresos"
        ordering = ["-fecha"]
        indexes = [models.Index(fields=["fecha"])]

    def __str__(self):
        return f"{self.inscripcion.quien} · {timezone.localtime(self.fecha):%d/%m %H:%M}"
