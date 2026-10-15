"""Registro de órdenes (Fase 09, ADR-024).

`build_draft()` arma la orden sin guardarla: expande perfiles, cotiza, avisa y planifica
los tubos. La usa la vista previa de la pantalla de recepción y `create_order()`, así lo
que se ve antes de guardar es exactamente lo que se guarda.

Cobro: la orden congela la cotización. Si la lista no tiene precio para algún examen, la
orden se registra igual con `pricing_pending=True` (el paciente no espera por un precio
sin cargar) y el aviso queda visible; cualquier otro error de cotización (descuento
vencido, lista inactiva) sí bloquea.
"""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.services.exchange import get_exchange_rate, round_money
from apps.billing.services.quoting import Quote, quote
from apps.catalog.selectors.catalog_queries import (
    calculation_input_tests,
    profile_tests,
    tests_without_parameters,
)
from apps.core.exceptions import ApplicationError
from apps.orders.models import Order, OrderItem
from apps.orders.services.numbering import next_order_number
from apps.orders.services.sample_planning import (
    PlannedTube,
    assign_samples,
    draw_order_key,
    needs_for_tests,
    plan_tubes,
)


@dataclass
class OrderDraft:
    items: list[tuple] = field(default_factory=list)  # [(Test, Profile | None)]
    quote: Quote | None = None
    missing_prices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tubes: list[PlannedTube] = field(default_factory=list)
    reference_currency: object = None
    exchange_rate: Decimal | None = None

    @property
    def tests(self) -> list:
        return [test for test, _ in self.items]

    @property
    def pricing_pending(self) -> bool:
        return self.quote is None

    @property
    def converted_total(self) -> Decimal | None:
        if self.quote is None or self.exchange_rate is None:
            return None
        return round_money(self.quote.total * self.exchange_rate,
                           currency=self.reference_currency)


def expand_items(*, tests: Sequence, profiles: Sequence) -> tuple[list[tuple], list[str]]:
    """Perfiles primero (en su orden), luego exámenes sueltos no incluidos ya."""
    items, seen, warnings = [], set(), []
    for profile in profiles:
        for test in profile_tests(profile=profile):
            if not test.is_active:
                warnings.append(f"{test.name} (de {profile.name}) está inactivo: se omitió.")
                continue
            if test.id not in seen:
                seen.add(test.id)
                items.append((test, profile))
    for test in tests:
        if test.id not in seen:
            seen.add(test.id)
            items.append((test, None))
    return items, warnings


def build_draft(
    *, tests: Sequence = (), profiles: Sequence = (), price_list=None,
    discounts: Sequence = (), reference_currency=None, on_date: datetime.date | None = None,
    authorized: bool = False, weight_kg=None, height_cm=None, urine_volume_24h_ml=None,
) -> OrderDraft:
    on_date = on_date or timezone.localdate()
    items, warnings = expand_items(tests=tests, profiles=profiles)
    draft = OrderDraft(items=items, warnings=warnings)
    if not items:
        return draft

    _quote_into(draft, tests=tests, profiles=profiles, price_list=price_list,
                discounts=discounts, on_date=on_date, authorized=authorized)
    if draft.quote is not None and reference_currency is not None \
            and reference_currency.pk != draft.quote.currency.pk:
        try:
            draft.exchange_rate = get_exchange_rate(
                from_currency=draft.quote.currency, to_currency=reference_currency,
                on_date=on_date,
            )
            draft.reference_currency = reference_currency
        except ApplicationError as exc:
            draft.warnings.append(exc.message)

    draft.warnings += _clinical_warnings(
        draft.tests, weight_kg=weight_kg, height_cm=height_cm,
        urine_volume_24h_ml=urine_volume_24h_ml,
    )
    needs, tube_warnings = needs_for_tests((test.code, test) for test in draft.tests)
    draft.warnings += tube_warnings
    draft.tubes = sorted(plan_tubes(needs), key=draw_order_key)
    return draft


def _quote_into(draft, *, tests, profiles, price_list, discounts, on_date, authorized):
    if price_list is None:
        draft.warnings.append("No hay una lista de precios vigente: la orden queda sin monto.")
        return
    try:
        draft.quote = quote(price_list=price_list, tests=tests, profiles=profiles,
                            discounts=discounts, on_date=on_date, authorized=authorized)
    except ApplicationError as exc:
        if "missing" not in exc.extra:
            raise
        draft.missing_prices = list(exc.extra["missing"])
        draft.warnings.append(
            f"Sin precio en la lista {price_list.code}: {', '.join(draft.missing_prices)}. "
            "La orden se registra con el monto pendiente."
        )
        return
    draft.warnings += draft.quote.warnings


def _clinical_warnings(tests, *, weight_kg, height_cm, urine_volume_24h_ml) -> list[str]:
    warnings = []
    empty = tests_without_parameters(tests=tests)
    if empty:
        warnings.append("Sin parámetros configurados (no se podrán cargar resultados): "
                        + ", ".join(empty) + ". Revise el examen en el catálogo.")
    anthropometric = [t.name for t in tests if t.requires_anthropometry]
    if anthropometric and not (weight_kg and height_cm and urine_volume_24h_ml):
        warnings.append(
            f"{', '.join(anthropometric)} necesita peso, talla y volumen de orina de 24 h "
            "para calcular: se pueden cargar después, antes de los resultados."
        )
    missing = calculation_input_tests(tests=tests)
    if missing:
        warnings.append(
            "Para los valores calculados faltan: "
            + ", ".join(sorted(t.name for t in missing)) + "."
        )
    fasting = [t.name for t in tests if t.requires_fasting]
    if fasting:
        warnings.append(f"Requieren ayuno: {', '.join(fasting)}.")
    return warnings


def _snapshot(draft: OrderDraft) -> dict:
    q = draft.quote
    if q is None:
        return {"missing_prices": draft.missing_prices}
    return {
        "on_date": q.on_date.isoformat(),
        "price_list": q.price_list_code,
        "currency": q.currency.code,
        "lines": [
            {"kind": line.kind, "code": line.code, "name": line.name,
             "base": str(line.base_amount), "discount": str(line.discount_amount),
             "amount": str(line.amount), "tests": list(line.included_tests),
             "notes": list(line.notes)}
            for line in q.lines
        ],
        "discounts": [
            {"code": d.code, "name": d.name, "scope": d.scope, "amount": str(d.amount),
             "line": d.line_code}
            for d in q.applied_discounts
        ],
        "warnings": list(q.warnings),
    }


def apply_draft_totals(order: Order, draft: OrderDraft) -> None:
    """Copia a la orden la cotización del borrador (sin guardar)."""
    q = draft.quote
    order.quote_snapshot = _snapshot(draft)
    order.pricing_pending = q is None
    order.price_list_code = q.price_list_code if q else ""
    order.currency_code = q.currency.code if q else ""
    order.subtotal = q.subtotal if q else None
    order.discount_total = q.discount_total if q else None
    order.total = q.total if q else None
    order.converted_currency_code = (draft.reference_currency.code
                                     if draft.exchange_rate is not None else "")
    order.exchange_rate = draft.exchange_rate
    order.converted_total = draft.converted_total


def create_order(
    *, patient, tests: Sequence = (), profiles: Sequence = (), price_list=None,
    discounts: Sequence = (), reference_currency=None, priority: str = Order.Priority.NORMAL,
    requested_by: str = "", notes: str = "", weight_kg=None, height_cm=None,
    urine_volume_24h_ml=None, created_by=None, authorized: bool = False,
    number: str | None = None, ordered_at=None, client_mutation_id=None,
) -> tuple[Order, list[str]]:
    """Registra la orden con sus exámenes y tubos. Devuelve `(orden, avisos)`.

    `number` y `ordered_at` existen para las órdenes creadas sin conexión (Fase 14): el
    número ya salió de un bloque reservado al dispositivo y la hora es la real del
    registro, no la de la sincronización. La cotización se arma con los precios y la tasa
    de **ese** día, no los de hoy. En línea se omiten y la orden toma el siguiente número
    de la secuencia.
    """
    if not tests and not profiles:
        raise ApplicationError("Agregue al menos un examen o perfil a la orden.")
    if not patient.is_active:
        raise ApplicationError("El paciente está inactivo.")
    inactive = [t.name for t in tests if not t.is_active]
    if inactive:
        raise ApplicationError(f"Exámenes inactivos: {', '.join(inactive)}.")

    now = ordered_at or timezone.now()
    draft = build_draft(
        tests=tests, profiles=profiles, price_list=price_list, discounts=discounts,
        reference_currency=reference_currency, on_date=timezone.localdate(now),
        authorized=authorized, weight_kg=weight_kg, height_cm=height_cm,
        urine_volume_24h_ml=urine_volume_24h_ml,
    )
    if not draft.items:
        raise ApplicationError("Los perfiles elegidos no tienen exámenes activos.")

    with transaction.atomic():
        order = Order(
            number=number or next_order_number(on_date=timezone.localdate(now)),
            patient=patient,
            priority=priority, ordered_at=now, requested_by=requested_by, notes=notes,
            weight_kg=weight_kg, height_cm=height_cm,
            urine_volume_24h_ml=urine_volume_24h_ml, created_by=created_by,
            client_mutation_id=client_mutation_id,
        )
        apply_draft_totals(order, draft)
        order.save()
        items = [
            OrderItem.objects.create(order=order, test=test, profile=profile,
                                     order_index=index, created_by=created_by)
            for index, (test, profile) in enumerate(draft.items)
        ]
        assign_samples(order=order, items=items, created_by=created_by)
    return order, draft.warnings
