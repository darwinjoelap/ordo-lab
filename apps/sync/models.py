"""Escritura offline y sincronización (Fase 14).

La idempotencia no vive en código: vive en el índice único de
`SyncQueueEntry.client_mutation_id`. El dispositivo genera ese UUID al encolar la
mutación y lo repite en cada reintento; el servidor hace `get_or_create` por él, así que
reenviar diez veces la misma captura deja un solo registro y un solo efecto.

Los números de orden offline salen de `OrderNumberBlock`: un rango del día reservado a un
dispositivo, tomado de la misma `OrderNumberSequence` que usa la recepción en línea. El
número es definitivo desde que la orden nace sin conexión — no hay renumeración, y por
tanto ninguna etiqueta queda con un código de barras que el sistema no conoce.
"""
from django.db import models

from apps.core.models import TenantBaseModel


class Device(TenantBaseModel):
    """Un dispositivo del laboratorio (tablet de toma, PC de recepción…).

    `device_id` lo genera el navegador la primera vez y lo guarda localmente; no es un
    secreto ni autentica nada (para eso está la sesión), sirve para saber de dónde vino
    cada mutación y a quién se le reservó qué numeración.
    """

    device_id = models.CharField("Identificador", max_length=64, unique=True)
    label = models.CharField("Nombre", max_length=80, blank=True, default="")
    last_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Último usuario",
    )
    last_seen_at = models.DateTimeField("Visto por última vez", null=True, blank=True)

    class Meta:
        verbose_name = "Dispositivo"
        verbose_name_plural = "Dispositivos"
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return self.label or self.device_id


class OrderNumberBlock(TenantBaseModel):
    """Rango de números de orden del día reservado a un dispositivo (ambos inclusive).

    Un dispositivo puede tener **varios** bloques del mismo día: cuando se le acaban los
    números y tiene conexión, pide otro. No hay unique por (dispositivo, día) por eso.
    El no solapamiento está garantizado en origen: todo bloque sale de avanzar
    `OrderNumberSequence`, la misma secuencia que usa la recepción en línea.

    `consumed` es informativo: lo reporta el cliente para que la pantalla de
    Sincronización muestre cuánto le queda. El servidor no depende de ese valor — los
    números del bloque ya salieron de la secuencia y no se los dará a nadie más.
    """

    device = models.ForeignKey(Device, on_delete=models.CASCADE,
                               related_name="number_blocks", verbose_name="Dispositivo")
    day = models.DateField("Día")
    from_value = models.PositiveSmallIntegerField("Desde")
    to_value = models.PositiveSmallIntegerField("Hasta")
    consumed = models.PositiveSmallIntegerField("Consumidos", default=0)

    class Meta:
        verbose_name = "Bloque de numeración"
        verbose_name_plural = "Bloques de numeración"
        ordering = ["-day", "from_value"]
        indexes = [models.Index(fields=["device", "day"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(to_value__gte=models.F("from_value")),
                                   name="ordernumberblock_range_ordered"),
        ]

    def __str__(self) -> str:
        return f"{self.device} {self.day:%d/%m/%Y}: {self.from_value:04d}-{self.to_value:04d}"

    @property
    def size(self) -> int:
        return self.to_value - self.from_value + 1


class SyncQueueEntry(TenantBaseModel):
    """Una mutación hecha sin conexión y recibida por el servidor."""

    class Kind(models.TextChoices):
        PACIENTE_NUEVO = "PACIENTE_NUEVO", "Paciente nuevo"
        ORDEN_NUEVA = "ORDEN_NUEVA", "Orden nueva"
        MUESTRA_TOMADA = "MUESTRA_TOMADA", "Muestra tomada"
        MUESTRA_RECHAZADA = "MUESTRA_RECHAZADA", "Muestra rechazada"
        RESULTADO_CAPTURADO = "RESULTADO_CAPTURADO", "Resultado capturado"

    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APLICADO = "APLICADO", "Aplicado"
        CONFLICTO = "CONFLICTO", "Conflicto"
        ERROR = "ERROR", "Error"

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="mutations",
                               verbose_name="Dispositivo")
    client_mutation_id = models.UUIDField("Id de la mutación", unique=True)
    kind = models.CharField("Tipo", max_length=20, choices=Kind.choices)
    payload = models.JSONField("Datos", default=dict, blank=True)
    # Cuándo ocurrió en el dispositivo: es la hora que se registra como `collected_at`,
    # `ordered_at` o `entered_at`, no la de llegada al servidor (`created_at`).
    client_created_at = models.DateTimeField("Ocurrió el")
    status = models.CharField("Estado", max_length=10, choices=Status.choices,
                              default=Status.PENDIENTE)
    applied_at = models.DateTimeField("Aplicada el", null=True, blank=True)
    error_detail = models.TextField("Detalle del error", blank=True, default="")
    # A qué objeto afectó, para mostrarlo en la pantalla sin volver a leer el payload.
    target_id = models.UUIDField("Objeto afectado", null=True, blank=True)
    target_label = models.CharField("Referencia", max_length=60, blank=True, default="")

    class Meta:
        verbose_name = "Mutación por sincronizar"
        verbose_name_plural = "Mutaciones por sincronizar"
        ordering = ["client_created_at"]
        indexes = [models.Index(fields=["status", "client_created_at"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.target_label or self.client_mutation_id}"

    @property
    def is_settled(self) -> bool:
        """Ya no se vuelve a aplicar (aplicada, o en manos de una persona)."""
        return self.status in (self.Status.APLICADO, self.Status.CONFLICTO)


class SyncConflict(TenantBaseModel):
    """Qué chocó al aplicar una mutación. En datos clínicos nunca se descarta en
    silencio: se registra el valor del dispositivo y el del servidor, y decide una
    persona."""

    class Reason(models.TextChoices):
        RESULTADO_VALIDADO = "RESULTADO_VALIDADO", "El resultado ya estaba validado"
        VERSION_VIEJA = "VERSION_VIEJA", "Otro usuario lo cambió primero"
        PACIENTE_DUPLICADO = "PACIENTE_DUPLICADO", "Posible paciente duplicado"
        ORDEN_CERRADA = "ORDEN_CERRADA", "La orden está anulada o entregada"
        MUESTRA_RECHAZADA = "MUESTRA_RECHAZADA", "La muestra fue rechazada"

    class Resolution(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por revisar"
        CLIENTE = "CLIENTE", "Se aplicó lo del dispositivo"
        SERVIDOR = "SERVIDOR", "Se mantuvo lo del servidor"
        MANUAL = "MANUAL", "Resuelto a mano"

    queue_entry = models.ForeignKey(SyncQueueEntry, on_delete=models.CASCADE,
                                    related_name="conflicts", verbose_name="Mutación")
    entity = models.CharField("Entidad", max_length=40)
    object_id = models.UUIDField("Objeto", null=True, blank=True)
    field = models.CharField("Campo", max_length=60, blank=True, default="")
    client_value = models.CharField("Valor del dispositivo", max_length=255, blank=True,
                                    default="")
    server_value = models.CharField("Valor del servidor", max_length=255, blank=True,
                                    default="")
    reason = models.CharField("Motivo", max_length=20, choices=Reason.choices)
    resolution = models.CharField("Resolución", max_length=10, choices=Resolution.choices,
                                  default=Resolution.PENDIENTE)
    resolved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Resuelto por",
    )
    resolved_at = models.DateTimeField("Resuelto el", null=True, blank=True)
    notes = models.CharField("Nota", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Conflicto de sincronización"
        verbose_name_plural = "Conflictos de sincronización"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["resolution", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.entity}.{self.field or '—'} ({self.get_reason_display()})"
