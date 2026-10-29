"""Toma y rechazo de muestras; el estado de la orden se deriva de sus muestras."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.orders.models import Order, Sample
from apps.orders.services.numbering import sample_identifiers

# Estados de orden que todavía dependen de la toma (luego manda la Fase 10).
PRE_ANALYTIC = (Order.Status.REGISTRADA, Order.Status.MUESTRA_TOMADA)


def refresh_order_status(order: Order) -> Order:
    """REGISTRADA ↔ MUESTRA_TOMADA según si todas las muestras vigentes se tomaron."""
    if order.status not in PRE_ANALYTIC:
        return order
    active = order.samples.exclude(status=Sample.Status.RECHAZADA)
    all_taken = active.exists() and not active.filter(
        status=Sample.Status.PENDIENTE
    ).exists()
    status = Order.Status.MUESTRA_TOMADA if all_taken else Order.Status.REGISTRADA
    if order.status != status:
        order.status = status
        order.save(update_fields=["status", "updated_at"])
    return order


def _check_order_open(order: Order) -> None:
    if order.is_cancelled:
        raise ApplicationError(f"La orden {order.number} está anulada.")


def collect_sample(*, sample: Sample, user=None, at=None) -> Sample:
    """`at` es la hora real de la toma: la usa la sincronización offline (Fase 14) para no
    registrar la hora en que llegó la mutación al servidor. Marcar dos veces es inocuo:
    la segunda no hace nada (idempotente por estado)."""
    _check_order_open(sample.order)
    if sample.status == Sample.Status.RECHAZADA:
        raise ApplicationError(f"La muestra {sample.number} fue rechazada.")
    if sample.status == Sample.Status.TOMADA:
        return sample
    with transaction.atomic():
        sample.status = Sample.Status.TOMADA
        sample.collected_at = at or timezone.now()
        sample.collected_by = user
        sample.save(update_fields=["status", "collected_at", "collected_by", "updated_at"])
        refresh_order_status(sample.order)
    return sample


def receive_sample(
    *, sample: Sample, origin: str, collected_at, origin_detail: str = "", user=None
) -> Sample:
    """Registra una muestra que **llegó ya tomada**.

    Se separa de `collect_sample` a propósito, aunque las dos la dejen en `TOMADA`: lo que
    la distingue es que la hora de toma la declara un tercero y que nadie del laboratorio
    la tomó. Por eso `collected_by` queda vacío — atribuir la toma a quien la recibió en el
    mostrador sería falsear la trazabilidad, y la firma de un informe se sostiene sobre ese
    dato. Quién la recibió queda en `created_by`.

    `collected_at` es obligatoria: una muestra que llega sin hora de toma no se puede
    interpretar, y poner la de ahora sería inventarla.
    """
    _check_order_open(sample.order)
    if origin not in Sample.Origin.values:
        raise ApplicationError(f"'{origin}' no es una procedencia válida.")
    if origin == Sample.Origin.LABORATORIO:
        raise ApplicationError(
            "Una muestra tomada en el laboratorio se marca con la toma normal, no aquí."
        )
    if sample.status == Sample.Status.RECHAZADA:
        raise ApplicationError(f"La muestra {sample.number} fue rechazada.")
    if collected_at is None:
        raise ApplicationError("Indique la hora en que se tomó la muestra.")
    if collected_at > timezone.now():
        raise ApplicationError("La hora de toma no puede estar en el futuro.")

    with transaction.atomic():
        sample.origin = origin
        sample.origin_detail = (origin_detail or "").strip()
        sample.status = Sample.Status.TOMADA
        sample.collected_at = collected_at
        sample.collected_by = None
        sample.save(update_fields=["origin", "origin_detail", "status", "collected_at",
                                   "collected_by", "updated_at"])
        refresh_order_status(sample.order)
    return sample


def collect_all(*, order: Order, user=None) -> int:
    """Marca como tomadas todas las muestras por tomar. Devuelve cuántas."""
    _check_order_open(order)
    pending = list(order.samples.filter(status=Sample.Status.PENDIENTE))
    with transaction.atomic():
        for sample in pending:
            collect_sample(sample=sample, user=user)
    return len(pending)


def reject_sample(*, sample: Sample, reason: str, user=None, at=None) -> Sample:
    """Rechaza la muestra y crea su reemplazo (número nuevo, mismos exámenes). El número
    rechazado nunca se reutiliza. Devuelve la muestra nueva. `at`: hora real del rechazo
    (sincronización offline, Fase 14)."""
    _check_order_open(sample.order)
    reason = (reason or "").strip()
    if not reason:
        raise ApplicationError("Indique el motivo del rechazo.")
    if sample.status == Sample.Status.RECHAZADA:
        raise ApplicationError(f"La muestra {sample.number} ya fue rechazada.")
    order = sample.order
    with transaction.atomic():
        sample.status = Sample.Status.RECHAZADA
        sample.rejected_at = at or timezone.now()
        sample.rejected_by = user
        sample.rejection_reason = reason
        sample.save(update_fields=["status", "rejected_at", "rejected_by",
                                   "rejection_reason", "updated_at"])
        sequence = order.samples.order_by("-sequence").values_list(
            "sequence", flat=True).first() + 1
        number, barcode = sample_identifiers(order_number=order.number, sequence=sequence)
        replacement = Sample.objects.create(
            order=order, sequence=sequence, number=number, barcode=barcode,
            container_type=sample.container_type, collection_label=sample.collection_label,
            is_exclusive=sample.is_exclusive, replaces=sample, created_by=user,
        )
        replacement.order_items.set(sample.order_items.all())
        refresh_order_status(order)
    return replacement
