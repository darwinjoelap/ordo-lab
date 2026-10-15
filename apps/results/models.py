"""Resultados (Fase 10, ADR-025).

- `Result`: un examen de la orden (1:1 con `OrderItem`). Se carga, se valida y, validado,
  **no se edita nunca** (corregir = rectificación, Fase 15).
- `ResultValue`: un parámetro. Sólo existe si tiene valor. Guarda la marca (alto, bajo,
  crítico…) y, al validar, **congela** el rango usado y su texto: un cambio posterior del
  rango no altera un informe ya emitido.
- `CriticalNotification`: quién confirmó un valor crítico y a quién se le avisó.
"""
from django.db import models
from django.db.models import Q

from apps.core.models import TenantBaseModel


class Result(TenantBaseModel):
    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por cargar"
        CARGADO = "CARGADO", "Cargado"
        VALIDADO = "VALIDADO", "Validado"
        RECTIFICADO = "RECTIFICADO", "Rectificado"

    order_item = models.OneToOneField("orders.OrderItem", on_delete=models.PROTECT,
                                      related_name="result", verbose_name="Examen")
    status = models.CharField("Estado", max_length=12, choices=Status.choices,
                              default=Status.PENDIENTE)
    entered_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="+", verbose_name="Cargado por")
    entered_at = models.DateTimeField("Cargado el", null=True, blank=True)
    validated_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="+",
                                     verbose_name="Validado por")
    validated_at = models.DateTimeField("Validado el", null=True, blank=True)
    # Se imprime debajo de ESTE examen en el informe (no al final de todo).
    observations = models.TextField("Observaciones", blank=True, default="")
    internal_note = models.TextField("Nota interna (no se imprime)", blank=True, default="")
    # Condición, peso, talla, orina, ISI y lote usados en los cálculos (copia al guardar).
    calculation_context = models.JSONField("Datos de cálculo", default=dict, blank=True)
    # Sincronización offline (Fase 14): sube en cada guardado. El dispositivo manda la
    # versión que tenía al capturar; si ya no coincide, alguien lo cambió primero y la
    # mutación queda como conflicto en vez de pisar el trabajo del otro.
    sync_version = models.PositiveIntegerField("Versión de sincronización", default=1)

    class Meta:
        verbose_name = "Resultado"
        verbose_name_plural = "Resultados"

    def __str__(self) -> str:
        return f"{self.order_item} ({self.get_status_display()})"

    @property
    def is_validated(self) -> bool:
        return self.status in (self.Status.VALIDADO, self.Status.RECTIFICADO)


class ResultValue(TenantBaseModel):
    class Flag(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        BAJO = "BAJO", "Bajo"
        ALTO = "ALTO", "Alto"
        CRITICO_BAJO = "CRITICO_BAJO", "Crítico bajo"
        CRITICO_ALTO = "CRITICO_ALTO", "Crítico alto"
        ANORMAL = "ANORMAL", "Anormal"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        CALCULADO = "CALCULADO", "Calculado"
        INSTRUMENTO = "INSTRUMENTO", "Instrumento"
        OFFLINE_SYNC = "OFFLINE_SYNC", "Sincronización"

    result = models.ForeignKey(Result, on_delete=models.CASCADE, related_name="values")
    parameter = models.ForeignKey("catalog.Parameter", on_delete=models.PROTECT,
                                  related_name="result_values", verbose_name="Parámetro")
    value_numeric = models.DecimalField("Valor", max_digits=18, decimal_places=6, null=True,
                                        blank=True)
    value_text = models.TextField("Texto", blank=True, null=True)  # noqa: DJ001
    value_low = models.DecimalField("Desde", max_digits=12, decimal_places=4, null=True,
                                    blank=True)
    value_high = models.DecimalField("Hasta", max_digits=12, decimal_places=4, null=True,
                                     blank=True)
    coded_option = models.ForeignKey("catalog.CodedOption", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="+")
    multi_options = models.ManyToManyField("catalog.CodedOption", blank=True,
                                           related_name="+")
    flag = models.CharField("Marca", max_length=13, choices=Flag.choices, blank=True,
                            default="")
    interpretation = models.CharField("Interpretación", max_length=255, blank=True,
                                      default="")
    reference_range = models.ForeignKey("catalog.ReferenceRange", on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="+",
                                        verbose_name="Rango usado")
    reference_text = models.CharField("Referencia impresa", max_length=255, blank=True,
                                      default="")
    source = models.CharField("Origen", max_length=12, choices=Source.choices,
                              default=Source.MANUAL)

    class Meta:
        verbose_name = "Valor de resultado"
        verbose_name_plural = "Valores de resultado"
        constraints = [
            models.UniqueConstraint(fields=["result", "parameter"],
                                    name="resultvalue_unique_parameter"),
            models.CheckConstraint(
                condition=Q(value_numeric__isnull=False) | Q(value_text__isnull=False)
                | Q(coded_option__isnull=False) | Q(value_low__isnull=False),
                name="resultvalue_has_value",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parameter.code} ({self.result})"

    @property
    def is_critical(self) -> bool:
        return self.flag in (self.Flag.CRITICO_BAJO, self.Flag.CRITICO_ALTO)


class CriticalNotification(TenantBaseModel):
    """Aviso de un valor crítico (quién avisó = `created_by`, cuándo = `notified_at`)."""

    class Method(models.TextChoices):
        LLAMADA = "LLAMADA", "Llamada telefónica"
        WHATSAPP = "WHATSAPP", "WhatsApp / mensaje"
        PRESENCIAL = "PRESENCIAL", "En persona"
        CORREO = "CORREO", "Correo"
        OTRO = "OTRO", "Otro"

    result_value = models.ForeignKey(ResultValue, on_delete=models.CASCADE,
                                     related_name="notifications")
    value_confirmed = models.BooleanField("Valor confirmado (repetido o verificado)")
    notified_to = models.CharField("Notificado a", max_length=150)
    method = models.CharField("Medio", max_length=12, choices=Method.choices)
    notified_at = models.DateTimeField("Notificado el")
    value_display = models.CharField("Valor notificado", max_length=100)
    notes = models.CharField("Notas", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Notificación de valor crítico"
        verbose_name_plural = "Notificaciones de valores críticos"
        ordering = ["-notified_at"]

    def __str__(self) -> str:
        return f"{self.result_value} → {self.notified_to}"
