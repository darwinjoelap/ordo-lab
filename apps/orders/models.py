"""Órdenes, exámenes ordenados y muestras (Fase 09, ADR-024).

- Número de orden diario `AAMMDD-NNNN`; cada tubo es `AAMMDD-NNNN-SS` y su código de
  barras son los mismos 12 dígitos sin guiones (Code 128, legible por analizadores).
- La orden congela la cotización (`quote_snapshot` + totales): un cambio posterior de
  precios no altera una orden ya registrada.
- Una muestra agrupa los exámenes que van en el mismo tubo; un examen puede requerir más
  de un tubo (depuración: envase de 24 h + tubo rojo), por eso la relación es M2M.
"""
from django.db import models

from apps.core.models import TenantBaseModel


class OrderNumberSequence(models.Model):
    """Contador de órdenes por día. Plumbing interno (mismo criterio que
    `PatientCodeSequence`): no hereda TenantBaseModel."""

    day = models.DateField("Día", unique=True)
    last_value = models.PositiveIntegerField("Último valor usado", default=0)

    class Meta:
        verbose_name = "Secuencia de órdenes"
        verbose_name_plural = "Secuencias de órdenes"

    def __str__(self) -> str:
        return f"{self.day:%d/%m/%Y}: {self.last_value}"


class Order(TenantBaseModel):
    class Status(models.TextChoices):
        REGISTRADA = "REGISTRADA", "Registrada"
        MUESTRA_TOMADA = "MUESTRA_TOMADA", "Muestra tomada"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        RESULTADOS_CARGADOS = "RESULTADOS_CARGADOS", "Resultados cargados"
        VALIDADA = "VALIDADA", "Validada"
        ENTREGADA = "ENTREGADA", "Entregada"
        ANULADA = "ANULADA", "Anulada"

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        URGENTE = "URGENTE", "Urgente"

    class Condition(models.TextChoices):
        """Condición del paciente que cambia sus rangos de referencia (Fase 10)."""
        NINGUNA = "NINGUNA", "Ninguna"
        EMBARAZO = "EMBARAZO", "Embarazo"

    number = models.CharField("Número", max_length=11, unique=True, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="orders",
        verbose_name="Paciente",
    )
    status = models.CharField(
        "Estado", max_length=20, choices=Status.choices, default=Status.REGISTRADA
    )
    priority = models.CharField(
        "Prioridad", max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    ordered_at = models.DateTimeField("Registrada el")
    requested_by = models.CharField("Médico solicitante", max_length=150, blank=True,
                                    default="")
    notes = models.TextField("Observaciones", blank=True, default="")

    # Datos del episodio (no del paciente): cambian entre visitas (01_MODELO_DATOS).
    weight_kg = models.DecimalField("Peso (kg)", max_digits=5, decimal_places=1,
                                    null=True, blank=True)
    height_cm = models.DecimalField("Talla (cm)", max_digits=5, decimal_places=1,
                                    null=True, blank=True)
    urine_volume_24h_ml = models.DecimalField(
        "Volumen de orina 24 h (mL)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    patient_condition = models.CharField(
        "Condición del paciente", max_length=10, choices=Condition.choices,
        default=Condition.NINGUNA,
    )

    # Cotización congelada (ADR-019/024).
    price_list_code = models.CharField("Lista de precios", max_length=30, blank=True,
                                       default="")
    currency_code = models.CharField("Moneda", max_length=3, blank=True, default="")
    subtotal = models.DecimalField("Subtotal", max_digits=14, decimal_places=2,
                                   null=True, blank=True)
    discount_total = models.DecimalField("Descuentos", max_digits=14, decimal_places=2,
                                         null=True, blank=True)
    total = models.DecimalField("Total", max_digits=14, decimal_places=2, null=True,
                                blank=True)
    converted_currency_code = models.CharField("Moneda de referencia", max_length=3,
                                               blank=True, default="")
    exchange_rate = models.DecimalField("Tasa", max_digits=20, decimal_places=8,
                                        null=True, blank=True)
    converted_total = models.DecimalField("Total en moneda de referencia", max_digits=18,
                                          decimal_places=2, null=True, blank=True)
    quote_snapshot = models.JSONField("Detalle de la cotización", default=dict, blank=True)
    pricing_pending = models.BooleanField(
        "Precio pendiente", default=False,
        help_text="La lista no tenía precio para algún examen al registrar la orden.",
    )

    is_paid = models.BooleanField("Pagada", default=False)
    paid_at = models.DateTimeField("Pagada el", null=True, blank=True)
    paid_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Cobrada por",
    )

    delivered_at = models.DateTimeField("Entregada el", null=True, blank=True)
    delivered_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Entregada por",
    )

    cancelled_at = models.DateTimeField("Anulada el", null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Anulada por",
    )
    cancel_reason = models.CharField("Motivo de anulación", max_length=255, blank=True,
                                     default="")

    # Sincronización offline (Fase 14). `client_mutation_id` es el id de la mutación que
    # creó esta orden sin conexión: único, así reenviar la cola nunca crea dos órdenes.
    # Vacío en las órdenes registradas en línea.
    client_mutation_id = models.UUIDField("Id de la mutación offline", null=True,
                                           blank=True, unique=True)
    sync_version = models.PositiveIntegerField("Versión de sincronización", default=1)

    class Meta:
        verbose_name = "Orden"
        verbose_name_plural = "Órdenes"
        ordering = ["-ordered_at"]
        indexes = [models.Index(fields=["status", "ordered_at"])]

    def __str__(self) -> str:
        return self.number

    @property
    def barcode(self) -> str:
        return self.number.replace("-", "")

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.Status.ANULADA


class OrderItem(TenantBaseModel):
    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        CARGADO = "CARGADO", "Cargado"
        VALIDADO = "VALIDADO", "Validado"
        ANULADO = "ANULADO", "Anulado"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    test = models.ForeignKey("catalog.Test", on_delete=models.PROTECT,
                             related_name="order_items", verbose_name="Examen")
    # Sólo para saber de qué paquete vino (el precio vive en el snapshot de la orden).
    profile = models.ForeignKey("catalog.Profile", on_delete=models.PROTECT, null=True,
                                blank=True, related_name="order_items",
                                verbose_name="Perfil")
    status = models.CharField("Estado", max_length=12, choices=Status.choices,
                              default=Status.PENDIENTE)
    order_index = models.PositiveSmallIntegerField("Orden", default=0)

    class Meta:
        verbose_name = "Examen de la orden"
        verbose_name_plural = "Exámenes de la orden"
        ordering = ["order", "order_index"]
        constraints = [
            models.UniqueConstraint(fields=["order", "test"], name="orderitem_unique_test"),
        ]

    def __str__(self) -> str:
        return f"{self.order.number} — {self.test.code}"


class Sample(TenantBaseModel):
    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por tomar"
        TOMADA = "TOMADA", "Tomada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="samples")
    sequence = models.PositiveSmallIntegerField("Secuencia")
    number = models.CharField("Número", max_length=14, unique=True, editable=False)
    barcode = models.CharField("Código de barras", max_length=12, unique=True,
                               editable=False)
    container_type = models.ForeignKey(
        "catalog.ContainerType", on_delete=models.PROTECT, related_name="samples",
        verbose_name="Tubo",
    )
    collection_label = models.CharField("Toma", max_length=30, blank=True, default="")
    is_exclusive = models.BooleanField(
        "Tubo propio", default=False, help_text="No recibe exámenes de otros requisitos."
    )
    order_items = models.ManyToManyField(OrderItem, related_name="samples",
                                         verbose_name="Exámenes")
    status = models.CharField("Estado", max_length=10, choices=Status.choices,
                              default=Status.PENDIENTE)
    collected_at = models.DateTimeField("Tomada el", null=True, blank=True)
    collected_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Tomada por",
    )
    rejected_at = models.DateTimeField("Rechazada el", null=True, blank=True)
    rejected_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Rechazada por",
    )
    rejection_reason = models.CharField("Motivo de rechazo", max_length=255, blank=True,
                                        default="")
    replaces = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="replaced_by", verbose_name="Reemplaza a",
    )

    class Meta:
        verbose_name = "Muestra"
        verbose_name_plural = "Muestras"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["order", "sequence"],
                                    name="sample_unique_sequence"),
        ]

    def __str__(self) -> str:
        return self.number


class LabelPrint(TenantBaseModel):
    """Registro de cada impresión de etiqueta (quién y cuándo; `created_by`/`created_at`)."""

    sample = models.ForeignKey(Sample, on_delete=models.CASCADE, related_name="prints")
    is_reprint = models.BooleanField("Reimpresión", default=False)

    class Meta:
        verbose_name = "Impresión de etiqueta"
        verbose_name_plural = "Impresiones de etiquetas"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.sample.number} ({self.created_at:%d/%m/%Y %I:%M %p})"
