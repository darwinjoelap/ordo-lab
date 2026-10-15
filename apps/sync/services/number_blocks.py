"""Reserva de numeración para órdenes creadas sin conexión (Fase 14).

Decisión de Darwin (2026-10-14): bloques reservados por dispositivo, no números
provisionales. El dispositivo pide su rango **mientras tiene conexión** y lo consume
offline, así el número de la orden es definitivo desde que nace y ninguna etiqueta queda
con un código de barras que el sistema no conoce.

Los números salen de avanzar `OrderNumberSequence` — la misma secuencia de la recepción
en línea — así que nunca se entrega dos veces el mismo número. El precio es que, si un
dispositivo no consume todo su bloque, quedan huecos en la numeración del día.
"""
from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.orders.models import Order, OrderNumberSequence
from apps.orders.services.numbering import MAX_ORDERS_PER_DAY
from apps.sync.models import Device, OrderNumberBlock

DEFAULT_BLOCK_SIZE = 20
MAX_BLOCK_SIZE = 200


def reserve_block(*, device: Device, day: datetime.date | None = None,
                  size: int = DEFAULT_BLOCK_SIZE, user=None) -> OrderNumberBlock:
    """Reserva un rango nuevo de números del día para `device`."""
    day = day or timezone.localdate()
    if not 1 <= size <= MAX_BLOCK_SIZE:
        raise ApplicationError(f"El bloque debe ser de 1 a {MAX_BLOCK_SIZE} números.")
    with transaction.atomic():
        sequence, _ = OrderNumberSequence.objects.select_for_update().get_or_create(day=day)
        if sequence.last_value + size > MAX_ORDERS_PER_DAY:
            raise ApplicationError(
                f"No quedan {size} números libres del día {day:%d/%m/%Y} "
                f"(máximo {MAX_ORDERS_PER_DAY} órdenes diarias)."
            )
        from_value = sequence.last_value + 1
        sequence.last_value += size
        sequence.save(update_fields=["last_value"])
        return OrderNumberBlock.objects.create(
            device=device, day=day, from_value=from_value, to_value=sequence.last_value,
            created_by=user,
        )


def number_from_block(*, device: Device, number: str) -> OrderNumberBlock:
    """Comprueba que `number` (AAMMDD-NNNN) salga de un bloque de ESTE dispositivo.

    Es la defensa contra un número inventado: si no pertenece a ningún bloque suyo, la
    mutación se rechaza en vez de crear una orden con un número que la secuencia podría
    volver a entregar a la recepción.
    """
    day, value = parse_order_number(number)
    block = OrderNumberBlock.objects.filter(
        device=device, day=day, from_value__lte=value, to_value__gte=value
    ).first()
    if block is None:
        raise ApplicationError(
            f"El número {number} no corresponde a un bloque reservado por este "
            "dispositivo."
        )
    if Order.objects.filter(number=number).exists():
        raise ApplicationError(f"Ya existe una orden con el número {number}.")
    return block


def parse_order_number(number: str) -> tuple[datetime.date, int]:
    """'261014-0007' → (date(2026, 10, 14), 7)."""
    try:
        head, tail = number.split("-")
        day = datetime.datetime.strptime(head, "%y%m%d").date()
        value = int(tail)
    except (AttributeError, ValueError) as exc:
        raise ApplicationError(f"Número de orden mal formado: {number!r}.") from exc
    if not 1 <= value <= MAX_ORDERS_PER_DAY:
        raise ApplicationError(f"Número de orden fuera de rango: {number}.")
    return day, value


def mark_consumed(*, block: OrderNumberBlock, consumed: int) -> OrderNumberBlock:
    """Informativo (lo reporta el cliente): cuántos números del bloque ya usó."""
    consumed = max(block.consumed, min(consumed, block.size))
    if consumed != block.consumed:
        block.consumed = consumed
        block.save(update_fields=["consumed", "updated_at"])
    return block
