"""Consultas de resultados (Fase 10)."""
from __future__ import annotations

from apps.results.models import Result, ResultValue
from apps.results.services.value_parsing import format_value

# Un resultado rectificado (Fase 15) sigue siendo un resultado validado: entra al informe
# y cuenta como valor anterior del paciente. Mismo criterio que `selectors/evolution.py`.
VALIDATED = (Result.Status.VALIDADO, Result.Status.RECTIFICADO)


def previous_values(*, patient, parameters, exclude_order) -> dict:
    """{parameter_id: {"text", "flag", "date", "numeric"}} con el último valor VALIDADO
    del paciente en otra orden (para comparar al cargar)."""
    values = (
        ResultValue.objects.filter(
            parameter__in=parameters, result__status__in=VALIDATED,
            result__order_item__order__patient=patient,
        )
        .exclude(result__order_item__order=exclude_order)
        .select_related("parameter", "coded_option", "result")
        .order_by("parameter_id", "-result__validated_at")
    )
    found: dict = {}
    for value in values:
        if value.parameter_id not in found:
            found[value.parameter_id] = {"text": format_value(value), "flag": value.flag,
                                         "date": value.result.validated_at,
                                         "numeric": value.value_numeric}
    return found


def result_value_of_order(*, order, pk) -> ResultValue:
    return ResultValue.objects.select_related("parameter", "result", "coded_option").get(
        pk=pk, result__order_item__order=order)


def result_of_order(*, order, pk) -> Result:
    return Result.objects.select_related("order_item__test", "entered_by").get(
        pk=pk, order_item__order=order)


def report_results(*, order) -> list[dict]:
    """Contenido imprimible de los exámenes **validados** de la orden (Fase 11), en orden
    de informe: sección → examen → grupo → parámetro. Usa la referencia y la marca
    congeladas al validar; omite parámetros no imprimibles y los que quedaron sin valor.
    Cada examen: {"code", "name", "section", "section_order", "page_break", "method",
    "validated_at", "validated_by", "observations", "rows": [...]}."""
    results = list(
        Result.objects.filter(order_item__order=order, status__in=VALIDATED)
        .exclude(order_item__status="ANULADO")
        .select_related("order_item__test__section", "order_item__test__method",
                        "validated_by")
        .prefetch_related("amendments")
        .order_by("order_item__test__section__order_index", "order_item__order_index")
    )
    values = (
        ResultValue.objects.filter(result__in=results, parameter__is_printable=True)
        .select_related("parameter__unit", "parameter__group", "coded_option")
        .prefetch_related("multi_options")
        .order_by("parameter__group__order_index", "parameter__order_index")
    )
    rows_by_result: dict = {}
    for value in values:
        parameter = value.parameter
        rows_by_result.setdefault(value.result_id, []).append({
            "code": parameter.code,
            "name": parameter.name,
            "group": parameter.group.name if parameter.group_id else "",
            "value": format_value(value),
            "unit": parameter.unit.symbol if parameter.unit_id else "",
            "flag": value.flag,
            "reference": value.reference_text,
            "interpretation": value.interpretation,
        })
    blocks = []
    for result in results:
        test = result.order_item.test
        blocks.append({
            "code": test.code,
            "name": test.name,
            "section": test.section.name,
            "section_order": test.section.order_index,
            "page_break": test.section.print_page_break,
            "method": test.method.name if test.method_id else "",
            "validated_at": result.validated_at,
            "validated_by": result.validated_by,
            "observations": result.observations,
            "amended": result.status == Result.Status.RECTIFICADO,
            "rows": rows_by_result.get(result.pk, []),
        })
    return blocks
