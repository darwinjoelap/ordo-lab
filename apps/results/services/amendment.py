"""Rectificación de resultados validados (Fase 15, ADR-035).

Un resultado validado es inmutable (`CLAUDE.md`). Corregirlo no es editarlo: es abrir una
**rectificación**, que congela cómo estaba antes y reabre el resultado para capturarlo de
nuevo. Al volver a validarlo queda en `RECTIFICADO` y el informe, que compara contenido
por huella, emite la versión siguiente con el sello correspondiente.

Lo que el paciente ya recibió no se toca: vive congelado en el `payload` del informe de su
versión, que queda *Reemplazado* pero nunca se borra.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.orders.models import Order
from apps.orders.services.order_progress import refresh_order_progress, set_item_status
from apps.results.models import Result, ResultAmendment
from apps.results.services.value_parsing import format_value

# Una orden anulada no se rectifica; una entregada sí — es el caso típico (el error se
# descubre después de entregar el informe).
BLOCKED_ORDER_STATUSES = (Order.Status.ANULADA,)


def _snapshot(result: Result) -> dict:
    """Cómo se veía el resultado antes de reabrirlo, con los valores ya formateados: es
    un registro para leer, no para recalcular."""
    values = (result.values.select_related("parameter", "parameter__unit", "coded_option")
              .prefetch_related("multi_options"))
    return {
        "status": result.status,
        "validated_at": (timezone.localtime(result.validated_at).isoformat()
                         if result.validated_at else ""),
        "validated_by": (result.validated_by.get_full_name()
                         or result.validated_by.get_username()) if result.validated_by
        else "",
        "observations": result.observations,
        "internal_note": result.internal_note,
        "values": [
            {
                "code": value.parameter.code,
                "name": value.parameter.name,
                "value": format_value(value),
                "unit": value.parameter.unit.symbol if value.parameter.unit_id else "",
                "flag": value.flag,
                "reference": value.reference_text,
            }
            for value in values
        ],
    }


@transaction.atomic
def amend_result(*, result: Result, reason: str, user=None) -> ResultAmendment:
    """Abre una rectificación y reabre el resultado para corregirlo.

    No cambia ningún valor: deja el resultado en `CARGADO` para que se capture de nuevo
    por la pantalla de siempre y se vuelva a validar.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ApplicationError("Indique el motivo de la rectificación.")
    order = result.order_item.order
    if order.status in BLOCKED_ORDER_STATUSES:
        raise ApplicationError(f"La orden {order.number} está anulada.")
    # Primero la rectificación abierta: en ese estado el resultado está reabierto (y por
    # tanto "no validado"), así que el otro mensaje sería cierto pero inútil — lo que el
    # usuario necesita saber es que ya hay una rectificación en curso.
    if result.amendments.filter(closed_at__isnull=True).exists():
        raise ApplicationError(
            f"{result.order_item.test.name} ya tiene una rectificación abierta: "
            "corrija los valores y valide de nuevo."
        )
    if not result.is_validated:
        raise ApplicationError(
            f"{result.order_item.test.name} no está validado: corríjalo directamente en "
            "la captura, sin rectificación."
        )

    last = (result.amendments.order_by("-version").values_list("version", flat=True)
            .first() or 0)
    amendment = ResultAmendment.objects.create(
        result=result, version=last + 1, reason=reason, snapshot=_snapshot(result),
        amended_at=timezone.now(), created_by=user,
    )
    result.status = Result.Status.CARGADO
    result.validated_by, result.validated_at = None, None
    result.sync_version += 1
    result.save(update_fields=["status", "validated_by", "validated_at", "sync_version",
                               "updated_at"])
    set_item_status(item=result.order_item, status="CARGADO")
    refresh_order_progress(order)
    return amendment


def close_open_amendments(result: Result, *, when=None) -> None:
    """Cierra la rectificación abierta al volver a validar. La llama `validate_results`."""
    result.amendments.filter(closed_at__isnull=True).update(
        closed_at=when or timezone.now())


def amended_test_names(*, order) -> list[str]:
    """Exámenes de la orden que fueron rectificados alguna vez (para el sello del
    informe). Sólo cuentan las rectificaciones ya cerradas: una abierta todavía no entra
    al informe, porque su resultado no está validado."""
    results = (Result.objects
               .filter(order_item__order=order, amendments__closed_at__isnull=False,
                       status=Result.Status.RECTIFICADO)
               .select_related("order_item__test")
               .order_by("order_item__order_index")
               .distinct())
    return [r.order_item.test.name for r in results]
