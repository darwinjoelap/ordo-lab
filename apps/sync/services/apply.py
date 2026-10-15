"""Aplicación de las mutaciones hechas sin conexión (Fase 14).

**Idempotencia.** No se resuelve con lógica sino con el índice único de
`SyncQueueEntry.client_mutation_id`: encolar es un `get_or_create` por ese id, y una
entrada ya aplicada no se vuelve a tocar. Reenviar la cola completa diez veces deja un
solo efecto. El payload de la primera recepción es el que manda: un reenvío no lo pisa.

**Conflictos.** En datos clínicos nunca se descarta en silencio (00_ARQUITECTURA §5). Un
resultado ya validado no se altera jamás: la mutación queda en `CONFLICTO` con el valor
del dispositivo y el del servidor, y decide una persona. Lo mismo si otro usuario cambió
el resultado primero (`sync_version` distinta).

**Qué NO hace el dispositivo.** Nada de cálculo clínico: `save_sheet()` corre aquí, en el
servidor, así que las fórmulas, los rangos por sexo/edad/condición y las marcas
alto/bajo/crítico salen de la única implementación que existe.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import (
    CAPTURE_ROLES,
    COLLECTION_ROLES,
    RECEPTION_ROLES,
    user_has_any_role,
)
from apps.billing.selectors.price_queries import default_price_list
from apps.catalog.models import Profile, Test
from apps.catalog.selectors.catalog_queries import parameters_for_tests
from apps.core.exceptions import ApplicationError
from apps.orders.models import Order, Sample
from apps.orders.services.order_creation import create_order
from apps.orders.services.sample_collection import collect_sample, reject_sample
from apps.patients.models import Patient
from apps.patients.services.patient_creation import register_patient
from apps.results.models import Result, ResultValue
from apps.results.services.result_capture import save_sheet
from apps.sync.models import Device, SyncConflict, SyncQueueEntry
from apps.sync.services.number_blocks import number_from_block

# Estados de orden en los que ya no se acepta una captura ni una toma llegada tarde.
CLOSED_ORDER_STATUSES = (Order.Status.ANULADA, Order.Status.ENTREGADA)

# La cola es una puerta de entrada más al dominio, así que repite el control de acceso de
# las pantallas: el auxiliar de toma puede marcar tubos, no capturar resultados ni
# registrar órdenes, aunque arme el JSON a mano.
ROLES_BY_KIND = {
    SyncQueueEntry.Kind.PACIENTE_NUEVO: RECEPTION_ROLES,
    SyncQueueEntry.Kind.ORDEN_NUEVA: RECEPTION_ROLES,
    SyncQueueEntry.Kind.MUESTRA_TOMADA: COLLECTION_ROLES,
    SyncQueueEntry.Kind.MUESTRA_RECHAZADA: COLLECTION_ROLES,
    SyncQueueEntry.Kind.RESULTADO_CAPTURADO: CAPTURE_ROLES,
}


@dataclass
class Outcome:
    """Resultado de aplicar una mutación, para que el cliente marque su cola."""

    entry: SyncQueueEntry
    conflicts: list[SyncConflict] = field(default_factory=list)

    @property
    def as_dict(self) -> dict:
        return {
            "client_mutation_id": str(self.entry.client_mutation_id),
            "status": self.entry.status,
            "target_id": str(self.entry.target_id) if self.entry.target_id else None,
            "target_label": self.entry.target_label,
            "error": self.entry.error_detail,
            "conflicts": [
                {"entity": c.entity, "field": c.field, "reason": c.reason,
                 "client_value": c.client_value, "server_value": c.server_value}
                for c in self.conflicts
            ],
        }


def receive(*, device: Device, mutations: list[dict], user=None) -> list[Outcome]:
    """Encola y aplica un lote. Devuelve un `Outcome` por mutación, en el mismo orden.

    El orden importa: el cliente manda sus mutaciones por `client_created_at`, así una
    orden creada offline encuentra ya aplicado al paciente que creó antes.
    """
    outcomes = []
    for raw in mutations:
        try:
            entry, created = _enqueue(device=device, raw=raw, user=user)
        except ApplicationError as exc:
            # Payload que no se puede ni encolar (sin id, tipo desconocido): se informa y
            # se sigue con el resto del lote.
            outcomes.append(Outcome(entry=_rejected_stub(raw, exc.message)))
            continue
        if entry.is_settled and not created:
            outcomes.append(Outcome(entry=entry,
                                     conflicts=list(entry.conflicts.all())))
            continue
        outcomes.append(_apply(entry, user=user))
    _touch(device, user=user)
    return outcomes


def retry_entry(entry: SyncQueueEntry, *, user=None) -> Outcome:
    """Vuelve a aplicar una mutación que falló, desde la pantalla de Sincronización.

    Sólo se reintenta lo que está en ERROR: una aplicada no se repite (idempotencia) y
    una en CONFLICTO espera a que una persona la revise, no a otro intento.
    """
    if entry.status != SyncQueueEntry.Status.ERROR:
        return Outcome(entry=entry, conflicts=list(entry.conflicts.all()))
    entry.error_detail = ""
    entry.status = SyncQueueEntry.Status.PENDIENTE
    entry.save(update_fields=["status", "error_detail", "updated_at"])
    return _apply(entry, user=user)


def _rejected_stub(raw: dict, message: str) -> SyncQueueEntry:
    """Entrada sin persistir, sólo para devolver el error de un payload inservible."""
    return SyncQueueEntry(client_mutation_id=raw.get("client_mutation_id") or
                          "00000000-0000-0000-0000-000000000000",
                          kind=raw.get("kind", ""), status=SyncQueueEntry.Status.ERROR,
                          error_detail=message, client_created_at=timezone.now())


def _enqueue(*, device: Device, raw: dict, user=None) -> tuple[SyncQueueEntry, bool]:
    kind = raw.get("kind")
    if not raw.get("client_mutation_id"):
        raise ApplicationError("La mutación no trae client_mutation_id.")
    if kind not in SyncQueueEntry.Kind.values:
        raise ApplicationError(f"Tipo de mutación desconocido: {kind!r}.")
    # Se castea a UUID a propósito: el id llega como texto del JSON y Django no coacciona
    # el atributo en memoria por asignarlo (sólo al escribirlo en la base), así que sin
    # esto `entry.client_mutation_id` sería un str y cualquier comparación en Python
    # contra el UUID guardado fallaría. De paso, un id mal formado se rechaza aquí con un
    # mensaje claro en vez de estallar dentro del query.
    try:
        mutation_id = uuid.UUID(str(raw["client_mutation_id"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ApplicationError(
            f"client_mutation_id no es un UUID válido: {raw['client_mutation_id']!r}."
        ) from exc
    return SyncQueueEntry.objects.get_or_create(
        client_mutation_id=mutation_id,
        defaults={
            "device": device, "kind": kind, "payload": raw.get("payload") or {},
            "client_created_at": _when(raw.get("client_created_at")),
            "created_by": user,
        },
    )


def _when(value) -> datetime.datetime:
    """ISO 8601 del dispositivo → datetime con zona. Sin fecha válida, ahora."""
    if not value:
        return timezone.now()
    try:
        moment = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    # Una hora futura (reloj del dispositivo adelantado) se recorta a ahora: evita
    # órdenes "registradas mañana" y resultados fechados en el futuro.
    return min(moment, timezone.now())


def _touch(device: Device, *, user=None) -> None:
    device.last_seen_at = timezone.now()
    device.last_user = user or device.last_user
    device.save(update_fields=["last_seen_at", "last_user", "updated_at"])


def _apply(entry: SyncQueueEntry, *, user=None) -> Outcome:
    """Aplica una entrada pendiente. Cada una en su propia transacción: una mutación que
    falla no tumba el resto del lote."""
    handler = _HANDLERS[entry.kind]
    outcome = Outcome(entry=entry)
    if not user_has_any_role(user, *ROLES_BY_KIND[entry.kind]):
        _fail(entry, f"Su rol no puede {entry.get_kind_display().lower()}.")
        return outcome
    try:
        with transaction.atomic():
            handler(entry, outcome, user)
            _settle(entry, outcome)
    except ApplicationError as exc:
        _fail(entry, exc.message)
    except (Test.DoesNotExist, Profile.DoesNotExist, Patient.DoesNotExist,
            Order.DoesNotExist, Sample.DoesNotExist, Result.DoesNotExist) as exc:
        _fail(entry, f"Referencia inexistente: {exc}")
    except (ValueError, TypeError, KeyError) as exc:
        _fail(entry, f"Datos de la mutación inválidos: {exc}")
    return outcome


def _settle(entry: SyncQueueEntry, outcome: Outcome) -> None:
    pending = [c for c in outcome.conflicts
               if c.resolution == SyncConflict.Resolution.PENDIENTE]
    entry.status = (SyncQueueEntry.Status.CONFLICTO if pending
                    else SyncQueueEntry.Status.APLICADO)
    entry.applied_at = timezone.now()
    entry.save(update_fields=["status", "applied_at", "target_id", "target_label",
                              "updated_at"])


def _fail(entry: SyncQueueEntry, message: str) -> None:
    """El error se guarda fuera de la transacción que se revirtió."""
    entry.status = SyncQueueEntry.Status.ERROR
    entry.error_detail = message
    entry.save(update_fields=["status", "error_detail", "updated_at"])


def _conflict(entry: SyncQueueEntry, outcome: Outcome, *, entity: str, reason: str,
              field_name: str = "", client_value="", server_value="", object_id=None,
              resolution: str = SyncConflict.Resolution.PENDIENTE,
              notes: str = "") -> SyncConflict:
    conflict = SyncConflict.objects.create(
        queue_entry=entry, entity=entity, object_id=object_id, field=field_name,
        client_value=str(client_value)[:255], server_value=str(server_value)[:255],
        reason=reason, resolution=resolution, notes=notes,
        created_by=entry.created_by,
    )
    outcome.conflicts.append(conflict)
    return conflict


# --------------------------------------------------------------------------- pacientes
def _apply_patient(entry: SyncQueueEntry, outcome: Outcome, user) -> None:
    data = dict(entry.payload)
    existing = Patient.objects.filter(client_mutation_id=entry.client_mutation_id).first()
    if existing is not None:  # ya se aplicó antes (reintento que llegó dos veces)
        return _target(entry, existing.pk, existing.internal_code)

    document_type = data.get("document_type", "")
    document_number = (data.get("document_number") or "").strip() or None
    if document_number:
        twin = Patient.objects.filter(document_type=document_type,
                                       document_number=document_number).first()
        if twin is not None:
            # Decisión de Darwin: documento idéntico → se reutiliza el existente y la
            # orden se le cuelga a él. Queda registrado (ya resuelto) para que se vea que
            # hubo una fusión, sin mandarlo a la cola de revisión.
            _conflict(entry, outcome, entity="Patient",
                      reason=SyncConflict.Reason.PACIENTE_DUPLICADO,
                      field_name="document_number", client_value=document_number,
                      server_value=twin.internal_code, object_id=twin.pk,
                      resolution=SyncConflict.Resolution.SERVIDOR,
                      notes="Se reutilizó el paciente que ya existía con ese documento.")
            return _target(entry, twin.pk, twin.internal_code)

    patient = register_patient(
        guardian_data=data.pop("guardian", None) or None, created_by=user,
        **_patient_fields(data),
    )
    Patient.objects.filter(pk=patient.pk).update(
        client_mutation_id=entry.client_mutation_id)

    if not document_number:
        # Sin documento no hay clave natural: si hay un homónimo del mismo sexo, se crea
        # igual pero queda marcado para que una persona decida si es el mismo.
        twin = Patient.objects.filter(
            first_name__iexact=patient.first_name, last_name__iexact=patient.last_name,
            sex=patient.sex,
        ).exclude(pk=patient.pk).first()
        if twin is not None:
            _conflict(entry, outcome, entity="Patient",
                      reason=SyncConflict.Reason.PACIENTE_DUPLICADO, field_name="nombre",
                      client_value=patient.internal_code, server_value=twin.internal_code,
                      object_id=patient.pk,
                      notes="Paciente sin documento con el mismo nombre y sexo que otro "
                            "ya registrado: revisar si son la misma persona.")
    _target(entry, patient.pk, patient.internal_code)


PATIENT_FIELDS = ("first_name", "last_name", "sex", "document_type", "document_number",
                  "birth_date", "declared_age_value", "declared_age_unit",
                  "declared_age_at", "address", "phone", "email")


def _patient_fields(data: dict) -> dict:
    fields = {key: data[key] for key in PATIENT_FIELDS if key in data}
    for key in ("birth_date", "declared_age_at"):
        if fields.get(key):
            fields[key] = datetime.date.fromisoformat(str(fields[key]))
    if data.get("locality_id"):
        from apps.masterdata.models import Locality
        fields["locality"] = Locality.objects.filter(pk=data["locality_id"]).first()
    return fields


# --------------------------------------------------------------------------- órdenes
def _apply_order(entry: SyncQueueEntry, outcome: Outcome, user) -> None:
    data = dict(entry.payload)
    existing = Order.objects.filter(client_mutation_id=entry.client_mutation_id).first()
    if existing is not None:
        return _target(entry, existing.pk, existing.number)

    number = data.get("number") or ""
    block = number_from_block(device=entry.device, number=number)
    patient = _resolve_patient(data)
    tests = list(Test.objects.filter(pk__in=data.get("test_ids") or []))
    profiles = list(Profile.objects.filter(pk__in=data.get("profile_ids") or []))

    # La cotización se congela con la lista vigente **el día en que se registró la
    # orden** en el dispositivo, no la de hoy. Descuentos y moneda de referencia no
    # viajan en la mutación offline: se recotiza desde la orden si hacen falta.
    price_list = default_price_list(on_date=timezone.localdate(entry.client_created_at))
    order, _warnings = create_order(
        patient=patient, tests=tests, profiles=profiles,
        price_list=price_list, priority=data.get("priority")
        or Order.Priority.NORMAL,
        requested_by=data.get("requested_by", ""), notes=data.get("notes", ""),
        weight_kg=data.get("weight_kg"), height_cm=data.get("height_cm"),
        urine_volume_24h_ml=data.get("urine_volume_24h_ml"), created_by=user,
        number=number, ordered_at=entry.client_created_at,
        client_mutation_id=entry.client_mutation_id,
    )
    block.consumed = min(block.consumed + 1, block.size)
    block.save(update_fields=["consumed", "updated_at"])
    _target(entry, order.pk, order.number)


def _resolve_patient(data: dict) -> Patient:
    """El paciente puede venir por su id (ya existía en el dispositivo) o por el id de la
    mutación que lo creó offline, aplicada antes en este mismo lote."""
    if data.get("patient_id"):
        return Patient.objects.get(pk=data["patient_id"])
    origin = data.get("patient_client_mutation_id")
    if not origin:
        raise ApplicationError("La orden no indica a qué paciente pertenece.")
    patient = Patient.objects.filter(client_mutation_id=origin).first()
    if patient is None:
        # Pasa si la mutación del paciente falló o llegó después: no se inventa nada.
        raise ApplicationError(
            "El paciente creado sin conexión para esta orden todavía no se pudo "
            "sincronizar."
        )
    return patient


# --------------------------------------------------------------------------- muestras
def _apply_collect(entry: SyncQueueEntry, outcome: Outcome, user) -> None:
    sample = _sample(entry.payload)
    if _order_closed(entry, outcome, sample):
        return
    if sample.status == Sample.Status.RECHAZADA:
        _conflict(entry, outcome, entity="Sample",
                  reason=SyncConflict.Reason.MUESTRA_RECHAZADA, field_name="status",
                  client_value="TOMADA", server_value=sample.status, object_id=sample.pk,
                  notes="El tubo se rechazó en el laboratorio mientras el dispositivo "
                        "estaba sin conexión: use el tubo de reemplazo.")
        return _target(entry, sample.pk, sample.number)
    collect_sample(sample=sample, user=user, at=entry.client_created_at)
    _target(entry, sample.pk, sample.number)


def _apply_reject(entry: SyncQueueEntry, outcome: Outcome, user) -> None:
    sample = _sample(entry.payload)
    if _order_closed(entry, outcome, sample):
        return
    if sample.status == Sample.Status.RECHAZADA:
        # Otro usuario (u otro dispositivo) ya lo rechazó: no se rechaza dos veces ni se
        # crea un segundo reemplazo.
        _conflict(entry, outcome, entity="Sample",
                  reason=SyncConflict.Reason.MUESTRA_RECHAZADA, field_name="status",
                  client_value="RECHAZADA", server_value=sample.rejection_reason,
                  object_id=sample.pk,
                  resolution=SyncConflict.Resolution.SERVIDOR,
                  notes="El tubo ya estaba rechazado; se mantuvo el rechazo registrado.")
        return _target(entry, sample.pk, sample.number)
    replacement = reject_sample(sample=sample, reason=entry.payload.get("reason", ""),
                                user=user, at=entry.client_created_at)
    _target(entry, replacement.pk, replacement.number)


def _sample(payload: dict) -> Sample:
    if payload.get("sample_id"):
        return Sample.objects.select_related("order").get(pk=payload["sample_id"])
    if payload.get("barcode"):
        return Sample.objects.select_related("order").get(barcode=payload["barcode"])
    raise ApplicationError("La mutación no indica de qué muestra se trata.")


def _order_closed(entry: SyncQueueEntry, outcome: Outcome, sample: Sample) -> bool:
    if sample.order.status not in CLOSED_ORDER_STATUSES:
        return False
    _conflict(entry, outcome, entity="Order",
              reason=SyncConflict.Reason.ORDEN_CERRADA, field_name="status",
              client_value=entry.get_kind_display(), server_value=sample.order.status,
              object_id=sample.order.pk)
    _target(entry, sample.pk, sample.number)
    return True


# --------------------------------------------------------------------------- resultados
def _apply_results(entry: SyncQueueEntry, outcome: Outcome, user) -> None:
    """Captura offline de una orden. Lo escrito llega en crudo: aquí se calcula, se
    resuelven rangos y se marcan altos/bajos/críticos."""
    data = dict(entry.payload)
    order = Order.objects.get(pk=data["order_id"])
    if order.status in CLOSED_ORDER_STATUSES:
        _conflict(entry, outcome, entity="Order",
                  reason=SyncConflict.Reason.ORDEN_CERRADA, field_name="status",
                  client_value="captura offline", server_value=order.status,
                  object_id=order.pk)
        return _target(entry, order.pk, order.number)

    entries = {str(k): v for k, v in (data.get("entries") or {}).items()}
    notes = data.get("notes") or {}
    versions = {str(k): v for k, v in (data.get("sync_versions") or {}).items()}

    blocked = _blocked_parameters(order, entries, versions, entry, outcome)
    for key in blocked:
        entries.pop(key, None)

    if entries or notes:
        save_sheet(order, entries=entries, notes=notes, user=user,
                   source=ResultValue.Source.OFFLINE_SYNC, at=entry.client_created_at)
    _target(entry, order.pk, order.number)


def _blocked_parameters(order, entries: dict, versions: dict, entry: SyncQueueEntry,
                        outcome: Outcome) -> set[str]:
    """Parámetros que NO se guardan, con su conflicto registrado: los de un resultado ya
    validado (inmutable) y los de un resultado que otro usuario cambió primero."""
    if not entries:
        return set()
    results = list(Result.objects.filter(order_item__order=order)
                   .select_related("order_item__test"))
    if not results:
        return set()
    # Mismo selector que usa la captura en línea: evita adivinar cómo se navega del
    # examen a sus parámetros (van por grupos) y respeta sus filtros.
    by_test: dict = {}
    labels: dict = {}
    for parameter in parameters_for_tests(tests=[r.order_item.test for r in results]):
        by_test.setdefault(parameter.test_id, set()).add(str(parameter.pk))
        labels[str(parameter.pk)] = parameter.name

    blocked: set[str] = set()
    for result in results:
        keys = by_test.get(result.order_item.test_id, set()) & set(entries)
        if not keys:
            continue
        test_name = result.order_item.test.name
        if result.is_validated:
            reason, server, note = (
                SyncConflict.Reason.RESULTADO_VALIDADO, "validado",
                f"{test_name} ya estaba validado: no se sobrescribe. Corregir exige una "
                "rectificación (Fase 15).")
        else:
            expected = versions.get(str(result.pk))
            if expected is None or int(expected) == result.sync_version:
                continue
            reason, server, note = (
                SyncConflict.Reason.VERSION_VIEJA, f"versión {result.sync_version}",
                f"{test_name} lo cambió otro usuario mientras el dispositivo estaba sin "
                "conexión.")
        for key in sorted(keys):
            _conflict(entry, outcome, entity="Result", reason=reason,
                      field_name=labels.get(key, key)[:60], client_value=entries[key],
                      server_value=server, object_id=result.pk, notes=note)
        blocked |= keys
    return blocked


def _target(entry: SyncQueueEntry, object_id, label: str) -> None:
    entry.target_id = object_id
    entry.target_label = (label or "")[:60]


_HANDLERS = {
    SyncQueueEntry.Kind.PACIENTE_NUEVO: _apply_patient,
    SyncQueueEntry.Kind.ORDEN_NUEVA: _apply_order,
    SyncQueueEntry.Kind.MUESTRA_TOMADA: _apply_collect,
    SyncQueueEntry.Kind.MUESTRA_RECHAZADA: _apply_reject,
    SyncQueueEntry.Kind.RESULTADO_CAPTURADO: _apply_results,
}
