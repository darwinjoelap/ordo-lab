"""Endpoints de sincronización (Fase 14). Las vistas sólo orquestan: leen el JSON,
llaman al service y devuelven JSON.

Autenticación por la sesión normal y CSRF activo: el cliente manda `X-CSRFToken`, igual
que htmx en el resto de la app. No hay tokens de dispositivo — `device_id` sirve para
saber de dónde vino cada mutación y a quién se le reservó numeración, no para autenticar.
El permiso fino lo aplica el service por tipo de mutación (`ROLES_BY_KIND`); aquí sólo se
exige ser alguien que opere órdenes.
"""
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import (
    CLINICAL_EDIT_ROLES,
    VIEW_ORDER_ROLES,
    role_required,
    user_has_any_role,
)
from apps.core.exceptions import ApplicationError
from apps.sync.models import Device, SyncConflict, SyncQueueEntry
from apps.sync.services.apply import receive, retry_entry
from apps.sync.services.number_blocks import DEFAULT_BLOCK_SIZE, mark_consumed, reserve_block

MAX_BATCH = 200


def _payload(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ApplicationError("El cuerpo de la petición no es JSON válido.") from exc
    if not isinstance(data, dict):
        raise ApplicationError("Se esperaba un objeto JSON.")
    return data


def _device(data: dict, user) -> Device:
    device_id = (data.get("device_id") or "").strip()
    if not device_id:
        raise ApplicationError("Falta device_id.")
    device, _ = Device.objects.get_or_create(
        device_id=device_id[:64],
        defaults={"label": (data.get("label") or "")[:80], "created_by": user},
    )
    return device


@role_required(*VIEW_ORDER_ROLES)
@require_POST
def mutations(request):
    """Recibe un lote de mutaciones y devuelve el desenlace de cada una.

    Es idempotente: reenviar el mismo lote (porque se cortó la respuesta) no repite
    ningún efecto, la respuesta vuelve a describir lo que ya se había aplicado.
    """
    try:
        data = _payload(request)
        device = _device(data, request.user)
        batch = data.get("mutations") or []
        if not isinstance(batch, list):
            raise ApplicationError("`mutations` debe ser una lista.")
        if len(batch) > MAX_BATCH:
            raise ApplicationError(f"Máximo {MAX_BATCH} mutaciones por envío.")
    except ApplicationError as exc:
        return JsonResponse({"error": exc.message}, status=400)

    outcomes = receive(device=device, mutations=batch, user=request.user)
    return JsonResponse({"results": [o.as_dict for o in outcomes]})


@role_required(*VIEW_ORDER_ROLES)
@require_POST
def number_block(request):
    """Reserva un rango de números de orden del día para el dispositivo, para que pueda
    registrar órdenes sin conexión con un número ya definitivo."""
    try:
        data = _payload(request)
        device = _device(data, request.user)
        size = int(data.get("size") or DEFAULT_BLOCK_SIZE)
        block = reserve_block(device=device, size=size, user=request.user)
    except ApplicationError as exc:
        return JsonResponse({"error": exc.message}, status=400)
    except (TypeError, ValueError):
        return JsonResponse({"error": "El tamaño del bloque debe ser un número."},
                            status=400)
    return JsonResponse({
        "day": block.day.isoformat(),
        "from": block.from_value, "to": block.to_value,
        "numbers": [f"{block.day:%y%m%d}-{n:04d}"
                    for n in range(block.from_value, block.to_value + 1)],
    })


@role_required(*VIEW_ORDER_ROLES)
@require_POST
def block_consumed(request):
    """El cliente informa cuántos números de su bloque ya usó (sólo para la pantalla)."""
    try:
        data = _payload(request)
        device = _device(data, request.user)
    except ApplicationError as exc:
        return JsonResponse({"error": exc.message}, status=400)
    block = device.number_blocks.filter(day=timezone.localdate()).order_by(
        "-from_value").first()
    if block is None:
        return JsonResponse({"error": "El dispositivo no tiene bloque de hoy."}, status=404)
    mark_consumed(block=block, consumed=int(data.get("consumed") or 0))
    return JsonResponse({"consumed": block.consumed, "size": block.size})


@role_required(*VIEW_ORDER_ROLES)
@require_GET
def status(request):
    """Contadores para el aviso de sin conexión y el badge del menú."""
    pending = SyncQueueEntry.objects.exclude(status=SyncQueueEntry.Status.APLICADO)
    return JsonResponse({
        "errores": pending.filter(status=SyncQueueEntry.Status.ERROR).count(),
        "conflictos": SyncConflict.objects.filter(
            resolution=SyncConflict.Resolution.PENDIENTE).count(),
        "por_aplicar": pending.filter(status=SyncQueueEntry.Status.PENDIENTE).count(),
    })


# --------------------------------------------------------------- pantalla (tramo C)
@role_required(*VIEW_ORDER_ROLES)
def panel(request):
    """Qué quedó sin subir, qué falló y qué choca con el trabajo de otro."""
    entries = (SyncQueueEntry.objects
               .exclude(status=SyncQueueEntry.Status.APLICADO)
               .select_related("device", "created_by"))
    return render(request, "sync/panel.html", {
        "entries": entries,
        "conflicts": (SyncConflict.objects
                      .filter(resolution=SyncConflict.Resolution.PENDIENTE)
                      .select_related("queue_entry", "queue_entry__device")),
        "recent": (SyncQueueEntry.objects
                   .filter(status=SyncQueueEntry.Status.APLICADO)
                   .select_related("device")
                   .order_by("-applied_at")[:15]),
        "blocks": Device.objects.filter(
            number_blocks__day=timezone.localdate()).distinct().prefetch_related(
            "number_blocks"),
        "can_resolve": user_has_any_role(request.user, *CLINICAL_EDIT_ROLES),
    })


def _entry(pk) -> SyncQueueEntry:
    try:
        return SyncQueueEntry.objects.get(pk=pk)
    except (SyncQueueEntry.DoesNotExist, ValueError, ValidationError) as exc:
        raise Http404("Mutación no encontrada.") from exc


@role_required(*VIEW_ORDER_ROLES)
@require_POST
def retry(request, pk):
    """Reintenta una mutación que falló. Útil cuando el error era de orden (p. ej. la
    orden llegó antes que el paciente que la sincronización creó después).

    El permiso fino lo vuelve a aplicar el service según el tipo de mutación.
    """
    entry = _entry(pk)
    outcome = retry_entry(entry, user=request.user)
    if outcome.entry.status == SyncQueueEntry.Status.APLICADO:
        messages.success(request, f"{entry.get_kind_display()} aplicada.")
    elif outcome.entry.status == SyncQueueEntry.Status.CONFLICTO:
        messages.warning(request, "Se aplicó en parte: quedó un conflicto por revisar.")
    else:
        messages.error(request, outcome.entry.error_detail or "No se pudo aplicar.")
    return redirect("sync:panel")


@role_required(*CLINICAL_EDIT_ROLES)
@require_POST
def resolve(request, pk):
    """Marca un conflicto como revisado. No "aplica lo del cliente": un resultado
    validado es inmutable, así que la corrección real es capturar de nuevo o emitir una
    rectificación (Fase 15). Esto registra quién lo revisó y qué decidió."""
    try:
        conflict = SyncConflict.objects.get(pk=pk)
    except (SyncConflict.DoesNotExist, ValueError, ValidationError) as exc:
        raise Http404("Conflicto no encontrado.") from exc
    conflict.resolution = (SyncConflict.Resolution.MANUAL
                           if request.POST.get("resolution") == "MANUAL"
                           else SyncConflict.Resolution.SERVIDOR)
    conflict.notes = (request.POST.get("notes") or conflict.notes)[:255]
    conflict.resolved_by = request.user
    conflict.resolved_at = timezone.now()
    conflict.save(update_fields=["resolution", "notes", "resolved_by", "resolved_at",
                                 "updated_at"])
    messages.success(request, "Conflicto marcado como revisado.")
    return redirect("sync:panel")
