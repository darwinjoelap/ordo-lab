"""Captura de resultados con cálculo en vivo (Fase 10, ADR-025).

`build_sheet()` arma la planilla de una orden: valores (los guardados o los que llegan del
formulario), parámetros calculados con el motor de fórmulas, rango resuelto por sexo, edad
en días y condición, marca (alto, bajo, crítico…) y valor anterior del paciente. La misma
función sirve para la vista previa en vivo (`persist=False`) y para guardar
(`persist=True`), así lo que se ve es lo que se guarda.

Reglas:
- Un resultado **validado** no se toca: sus valores quedan congelados.
- Tampoco se puede cambiar un insumo que alimenta un calculado ya validado.
- Un examen está «cargado» cuando tiene todos sus parámetros no opcionales y no
  calculados; un calculado que no se pudo calcular queda con su motivo (aviso).
- Cargar sin tubo tomado se permite con aviso (decisión de Darwin, Fase 10).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.selectors.catalog_queries import (
    calculated_formulas,
    observation_templates_by_test,
    parameters_for_tests,
)
from apps.catalog.services.formula_engine import (
    evaluate_calculated_parameters,
    quantize_for_display,
)
from apps.catalog.services.reagent_lots import current_isi
from apps.catalog.services.reference_resolver import resolve_reference_range
from apps.core.exceptions import ApplicationError
from apps.orders.selectors.order_queries import items_for_results
from apps.orders.services.order_progress import refresh_order_progress, set_item_status
from apps.patients.services.patient_age import patient_age_days
from apps.results.models import Result, ResultValue
from apps.results.selectors.result_queries import previous_values
from apps.results.services.interpretation import Assessment, assess
from apps.results.services.value_parsing import (
    VT_CALCULATED,
    VT_MULTI,
    VT_OPTIONS,
    ParsedValue,
    format_value,
    input_text,
    parse_input,
)

NINGUNA = "NINGUNA"
TAKEN = "TOMADA"


@dataclass
class Row:
    parameter: object
    parsed: ParsedValue
    display: str = ""
    input: object = ""
    assessment: Assessment = field(default_factory=Assessment)
    reference_range: object = None
    reference_text: str = ""
    calc_note: str = ""
    previous: dict | None = None
    stored: ResultValue | None = None
    error: str = ""
    raw: object = None  # lo escrito, si no se pudo leer (se vuelve a mostrar)

    @property
    def is_calculated(self) -> bool:
        return self.parameter.value_type == VT_CALCULATED

    @property
    def previous_delta(self) -> float | None:
        """Variación (%) del valor escrito contra el anterior validado (Fase 11e)."""
        before = (self.previous or {}).get("numeric")
        now = self.parsed.numeric
        if before in (None, 0) or now is None:
            return None
        return float((now - before) / abs(before) * 100)

    @property
    def is_critical(self) -> bool:
        return self.assessment.flag in ("CRITICO_BAJO", "CRITICO_ALTO")

    @property
    def critical_notified(self) -> bool:
        """Hay un aviso confirmado para **este** valor (si el valor cambió, hay que avisar
        de nuevo)."""
        return bool(self.stored and any(
            n.value_confirmed and n.value_display == self.display
            for n in self.stored.notifications.all()))


@dataclass
class Block:
    item: object
    result: Result
    rows: list[Row] = field(default_factory=list)
    sample_taken: bool = True
    templates: list = field(default_factory=list)  # observaciones predefinidas
    observations: str = ""   # se imprime debajo de este examen
    internal_note: str = ""  # no se imprime

    @property
    def missing(self) -> list[str]:
        return [r.parameter.name for r in self.rows
                if not r.is_calculated and not r.parameter.is_optional and r.parsed.is_empty]

    @property
    def has_values(self) -> bool:
        return any(not r.parsed.is_empty for r in self.rows)

    @property
    def is_complete(self) -> bool:
        return self.has_values and not self.missing

    @property
    def pending_criticals(self) -> list[Row]:
        return [r for r in self.rows if r.is_critical and not r.critical_notified]


@dataclass
class Sheet:
    order: object
    blocks: list[Block]
    context: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def ensure_results(order) -> list[tuple]:
    """[(OrderItem, Result)] creando los `Result` que falten."""
    pairs = []
    for item in items_for_results(order=order):
        result, _ = Result.objects.get_or_create(order_item=item)
        pairs.append((item, result))
    return pairs


def _stored_parsed(value: ResultValue | None) -> ParsedValue:
    if value is None:
        return ParsedValue()
    return ParsedValue(numeric=value.value_numeric, text=value.value_text, low=value.value_low,
                       high=value.value_high, option=value.coded_option,
                       options=list(value.multi_options.all()))


def _order_context(order) -> tuple[dict, dict, list[str]]:
    """(contexto para fórmulas, copia para guardar, avisos)."""
    warnings = []
    lot = current_isi()
    isi = lot.isi if lot else None
    if lot and lot.expired:
        warnings.append(f"El lote de tromboplastina vigente ({lot.lot_number}) está vencido.")
    context = {"peso": order.weight_kg, "talla": order.height_cm,
               "volumen_orina_24h": order.urine_volume_24h_ml, "isi": isi}
    snapshot = {key: (str(value) if value is not None else None)
                for key, value in context.items()}
    snapshot["lote_tromboplastina"] = lot.lot_number if lot else None
    snapshot["condicion"] = order.patient_condition
    return context, snapshot, warnings


class _RangeResolver:
    def __init__(self, order):
        patient = order.patient
        self.sex = patient.sex
        self.age_days = patient_age_days(patient, as_of=timezone.localdate(order.ordered_at))
        self.condition = order.patient_condition
        self.cache: dict = {}

    def __call__(self, parameter):
        if parameter.pk not in self.cache:
            found = resolve_reference_range(parameter=parameter, sex=self.sex,
                                            age_days=self.age_days, condition=self.condition)
            if found is None and self.condition != NINGUNA:
                found = resolve_reference_range(parameter=parameter, sex=self.sex,
                                                age_days=self.age_days, condition=NINGUNA)
            self.cache[parameter.pk] = found
        return self.cache[parameter.pk]


def build_sheet(order, *, entries: dict | None = None, notes: dict | None = None) -> Sheet:
    """Planilla de la orden. `entries`: {str(parameter_id): valor crudo | [ids]} del
    formulario; `notes`: {str(result_id): {"observations", "internal_note"}}. Lo que no
    viene se toma de lo guardado."""
    entries = entries or {}
    notes = notes or {}
    pairs = ensure_results(order)
    parameters = parameters_for_tests(tests=[item.test for item, _ in pairs])
    by_test: dict = {}
    for parameter in parameters:
        by_test.setdefault(parameter.test_id, []).append(parameter)
    stored = {
        (v.result_id, v.parameter_id): v
        for v in ResultValue.objects.filter(result__in=[r for _, r in pairs])
        .select_related("coded_option", "parameter").prefetch_related("multi_options",
                                                                        "notifications")
    }
    context, snapshot, warnings = _order_context(order)
    sheet = Sheet(order=order, blocks=[], context=snapshot, warnings=warnings)
    resolve = _RangeResolver(order)
    previous = previous_values(patient=order.patient, parameters=parameters,
                               exclude_order=order)
    templates = observation_templates_by_test(tests=[item.test for item, _ in pairs])

    numbers: dict[str, Decimal | None] = {}
    for item, result in pairs:
        typed = {} if result.is_validated else notes.get(str(result.pk), {})
        block = Block(item=item, result=result,
                      sample_taken=any(s.status == TAKEN for s in item.samples.all()),
                      templates=templates.get(item.test_id, []),
                      observations=typed.get("observations", result.observations).strip(),
                      internal_note=typed.get("internal_note", result.internal_note).strip())
        for parameter in by_test.get(item.test_id, []):
            row = Row(parameter=parameter, parsed=ParsedValue(),
                      stored=stored.get((result.pk, parameter.pk)),
                      previous=previous.get(parameter.pk))
            key = str(parameter.pk)
            if parameter.value_type != VT_CALCULATED:
                if key in entries and not result.is_validated:
                    try:
                        row.parsed = parse_input(parameter, entries[key], options=_options(
                            parameter))
                    except ApplicationError as exc:
                        row.error = exc.message
                        row.raw = entries[key]
                        sheet.errors.append(exc.message)
                        row.parsed = _stored_parsed(row.stored)
                else:
                    row.parsed = _stored_parsed(row.stored)
                numbers[parameter.code] = row.parsed.numeric
            block.rows.append(row)
        sheet.blocks.append(block)

    _calculate(sheet, parameters, numbers, context)
    for block in sheet.blocks:
        for row in block.rows:
            _finish_row(row, resolve)
    missing_samples = [b.item.test.name for b in sheet.blocks
                       if not b.sample_taken and b.has_values and not b.result.is_validated]
    if missing_samples:
        sheet.warnings.append("Resultados cargados sin tubo marcado como tomado: "
                              + ", ".join(missing_samples)
                              + ". Márquelo en la orden (Ver orden → Tomada).")
    return sheet


def _options(parameter) -> dict:
    if parameter.option_set_id is None:
        return {}
    return {str(o.pk): o for o in parameter.option_set.options.all()}


def _calculate(sheet: Sheet, parameters, numbers: dict, context: dict) -> None:
    formulas = calculated_formulas(parameters=parameters)
    if not formulas:
        return
    # Los calculados ya validados entran congelados; no se recalculan.
    frozen = {}
    for block in sheet.blocks:
        for row in block.rows:
            if row.is_calculated and block.result.is_validated:
                frozen[row.parameter.code] = row.stored.value_numeric if row.stored else None
    numbers.update(frozen)
    outcome = evaluate_calculated_parameters(
        formulas={c: f for c, f in formulas.items() if c not in frozen},
        values=numbers, context=context,
    )
    for block in sheet.blocks:
        for row in block.rows:
            if not row.is_calculated:
                continue
            if row.parameter.code in frozen:
                row.parsed = _stored_parsed(row.stored)
                continue
            calc = outcome.get(row.parameter.code)
            if calc is None or calc.value is None:
                row.calc_note = calc.reason if calc else ""
                continue
            row.parsed = ParsedValue(numeric=quantize_for_display(
                calc.value, decimals=row.parameter.decimals))


def _finish_row(row: Row, resolve) -> None:
    parameter = row.parameter
    row.reference_range = resolve(parameter)
    row.reference_text = row.reference_range.display_text if row.reference_range else ""
    if row.error:
        row.input = row.raw
        return
    parsed = row.parsed
    if parsed.is_empty:
        row.input = [] if parameter.value_type == VT_MULTI else ""
        return
    number = parsed.comparable if parameter.value_type not in VT_OPTIONS else None
    row.assessment = assess(number=number, option=parsed.option,
                            reference_range=row.reference_range)
    row.display = _display(parameter, parsed)
    if parameter.value_type == VT_MULTI:
        row.input = [str(o.pk) for o in parsed.options]
    elif parameter.value_type in VT_OPTIONS:
        row.input = str(parsed.option.pk)
    elif row.stored is not None and _same(row.stored, parsed):
        row.input = input_text(row.stored)
    else:
        row.input = row.display


def _display(parameter, parsed: ParsedValue) -> str:
    fake = ResultValue(parameter=parameter, value_numeric=parsed.numeric,
                       value_text=parsed.text, value_low=parsed.low, value_high=parsed.high,
                       coded_option=parsed.option)
    return format_value(fake)


def _same(value: ResultValue, parsed: ParsedValue) -> bool:
    return (value.value_numeric == parsed.numeric and (value.value_text or None) == parsed.text
            and value.value_low == parsed.low and value.value_high == parsed.high
            and value.coded_option_id == (parsed.option.pk if parsed.option else None)
            and {o.pk for o in value.multi_options.all()} == {o.pk for o in parsed.options})


# --------------------------------------------------------------------------- guardar
def _frozen_inputs(sheet: Sheet) -> dict[str, str]:
    """{código insumo: nombre del calculado validado que lo usa}."""
    guarded = {}
    for block in sheet.blocks:
        if not block.result.is_validated:
            continue
        for row in block.rows:
            if row.is_calculated:
                for dependency in row.parameter.depends_on.all():
                    guarded[dependency.code] = row.parameter.name
    return guarded


@transaction.atomic
def save_sheet(order, *, entries: dict, notes: dict | None = None, user=None,
               source: str | None = None, at=None) -> Sheet:
    """Guarda lo capturado. Lanza `ApplicationError` si hay valores inválidos o se intenta
    cambiar un insumo de un calculado ya validado.

    `source` y `at` son para la sincronización offline (Fase 14): marcan los valores
    manuales como `OFFLINE_SYNC` y registran la hora real de la captura en el
    dispositivo, no la de la sincronización. El cálculo, los rangos y las marcas se
    resuelven **aquí**: el dispositivo sólo guardó lo escrito en crudo.
    """
    if order.is_cancelled:
        raise ApplicationError(f"La orden {order.number} está anulada.")
    sheet = build_sheet(order, entries=entries, notes=notes)
    if sheet.errors:
        raise ApplicationError(" ".join(sheet.errors), extra={"sheet": sheet})
    guarded = _frozen_inputs(sheet)
    now = at or timezone.now()
    for block in sheet.blocks:
        if block.result.is_validated:
            continue
        changed = _save_notes(block)
        for row in block.rows:
            if not _row_changed(row):
                if row.stored is not None and not row.parsed.is_empty:
                    _refresh_assessment(row)
                continue
            if row.parameter.code in guarded:
                raise ApplicationError(
                    f"{row.parameter.name} alimenta a {guarded[row.parameter.code]}, que ya "
                    "está validado: no se puede cambiar (corrija con una rectificación)."
                )
            _persist_row(block.result, row, source=source)
            changed = changed or not row.is_calculated
        _update_status(block, sheet, user=user if changed else None, now=now, bump=changed)
    refresh_order_progress(order)
    return sheet


def _save_notes(block: Block) -> bool:
    result = block.result
    if (result.observations, result.internal_note) == (block.observations,
                                                       block.internal_note):
        return False
    result.observations, result.internal_note = block.observations, block.internal_note
    result.save(update_fields=["observations", "internal_note", "updated_at"])
    return True


def _row_changed(row: Row) -> bool:
    if row.stored is None:
        return not row.parsed.is_empty
    return row.parsed.is_empty or not _same(row.stored, row.parsed)


def _refresh_assessment(row: Row) -> None:
    value = row.stored
    new = (row.assessment.flag, row.assessment.interpretation, row.reference_range,
           row.reference_text)
    old = (value.flag, value.interpretation, value.reference_range, value.reference_text)
    if new != old:
        (value.flag, value.interpretation, value.reference_range,
         value.reference_text) = new
        value.save(update_fields=["flag", "interpretation", "reference_range",
                                  "reference_text", "updated_at"])


def _persist_row(result: Result, row: Row, *, source: str | None = None) -> None:
    if row.parsed.is_empty:
        if row.stored is not None:
            row.stored.delete()
            row.stored = None
        return
    parsed = row.parsed
    value = row.stored or ResultValue(result=result, parameter=row.parameter)
    value.value_numeric = parsed.numeric
    value.value_text = parsed.text
    value.value_low, value.value_high = parsed.low, parsed.high
    value.coded_option = parsed.option
    value.flag = row.assessment.flag
    value.interpretation = row.assessment.interpretation
    value.reference_range = row.reference_range
    value.reference_text = row.reference_text
    # Un calculado siempre es CALCULADO, lo haya disparado la captura en línea o la
    # sincronización: el valor lo produjo el motor de fórmulas del servidor.
    value.source = (ResultValue.Source.CALCULADO if row.is_calculated
                    else (source or ResultValue.Source.MANUAL))
    value.save()
    value.multi_options.set(parsed.options)
    row.stored = value


def _update_status(block: Block, sheet: Sheet, *, user, now, bump: bool = False) -> None:
    result = block.result
    fields = ["status", "calculation_context", "updated_at"]
    result.calculation_context = sheet.context
    result.status = Result.Status.CARGADO if block.is_complete else Result.Status.PENDIENTE
    if user is not None:
        result.entered_by, result.entered_at = user, now
        fields += ["entered_by", "entered_at"]
    if bump:
        # Sube en cada guardado con cambios reales: la sincronización offline (Fase 14)
        # compara esta versión con la que tenía el dispositivo al capturar para saber si
        # alguien más lo cambió mientras tanto.
        result.sync_version += 1
        fields.append("sync_version")
    result.save(update_fields=fields)
    item_status = {Result.Status.CARGADO: "CARGADO"}.get(
        result.status, "EN_PROCESO" if block.has_values else "PENDIENTE")
    set_item_status(item=block.item, status=item_status)

