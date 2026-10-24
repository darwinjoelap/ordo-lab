"""Validación de resultados y aviso de valores críticos (Fase 10, ADR-025).

Validar = recalcular con los rangos vigentes, **congelar** rango y texto de referencia en
cada valor y cerrar el resultado: desde ahí es inmutable (corregir = rectificación,
Fase 15). No se valida si:
- faltan parámetros obligatorios;
- hay un valor crítico sin aviso registrado (valor confirmado + a quién se avisó);
- el laboratorio exige doble validación y quien valida es quien cargó.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.orders.services.order_progress import refresh_order_progress, set_item_status
from apps.results.models import CriticalNotification, Result, ResultValue
from apps.results.services.amendment import close_open_amendments
from apps.results.services.result_capture import build_sheet, save_sheet
from apps.results.services.value_parsing import format_value
from apps.settings_lab.models import TenantSettings


def _check_block(block, *, user) -> None:
    result = block.result
    name = block.item.test.name
    if result.is_validated:
        raise ApplicationError(f"{name} ya está validado.")
    if not block.is_complete:
        missing = ", ".join(block.missing) or "todos los valores"
        raise ApplicationError(f"{name}: faltan {missing}.")
    pending = block.pending_criticals
    if pending:
        raise ApplicationError(
            f"{name}: registre el aviso del valor crítico de "
            + ", ".join(r.parameter.name for r in pending) + " antes de validar."
        )
    if TenantSettings.get_solo().require_second_validation and result.entered_by_id == getattr(
            user, "pk", None):
        raise ApplicationError(
            f"{name}: el laboratorio exige doble validación; debe validarlo una persona "
            "distinta a la que cargó."
        )


@transaction.atomic
def validate_results(*, order, result_ids: list | None = None, user=None) -> list[Result]:
    """Valida los resultados indicados (o todos los cargados de la orden)."""
    if order.is_cancelled:
        raise ApplicationError(f"La orden {order.number} está anulada.")
    save_sheet(order, entries={}, user=None)  # rangos y marcas al día antes de congelar
    sheet = build_sheet(order)
    wanted = {str(i) for i in result_ids} if result_ids else None
    blocks = [b for b in sheet.blocks
              if (wanted is None and b.result.status == Result.Status.CARGADO)
              or (wanted is not None and str(b.result.pk) in wanted)]
    if not blocks:
        raise ApplicationError("No hay resultados cargados para validar.")
    for block in blocks:
        _check_block(block, user=user)
    now = timezone.now()
    for block in blocks:
        result = block.result
        # Si venía de una rectificación (Fase 15) queda en RECTIFICADO, no en VALIDADO:
        # el informe lo sella y la evolución del paciente ya contaba con ese estado.
        amended = result.amendments.filter(closed_at__isnull=True).exists()
        result.status = Result.Status.RECTIFICADO if amended else Result.Status.VALIDADO
        result.validated_by, result.validated_at = user, now
        result.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
        if amended:
            close_open_amendments(result, when=now)
        set_item_status(item=block.item, status="VALIDADO")
    refresh_order_progress(order)
    return [b.result for b in blocks]


@transaction.atomic
def notify_critical(*, value: ResultValue, value_confirmed: bool, notified_to: str,
                    method: str, notes: str = "", user=None) -> CriticalNotification:
    """Registra el aviso de un valor crítico. El valor debe estar confirmado."""
    if not value.is_critical:
        raise ApplicationError("El valor no es crítico.")
    if value.result.is_validated:
        raise ApplicationError("El resultado ya está validado.")
    if not value_confirmed:
        raise ApplicationError("Confirme el valor (repetido o verificado) antes de avisar.")
    notified_to = (notified_to or "").strip()
    if not notified_to:
        raise ApplicationError("Indique a quién se avisó.")
    if method not in CriticalNotification.Method.values:
        raise ApplicationError("Medio de aviso no válido.")
    return CriticalNotification.objects.create(
        result_value=value, value_confirmed=True, notified_to=notified_to, method=method,
        notes=(notes or "").strip(), notified_at=timezone.now(),
        value_display=format_value(value), created_by=user,
    )
