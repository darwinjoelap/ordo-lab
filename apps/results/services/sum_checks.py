"""Avisos de sumas que deben cuadrar (ADR-042).

La fórmula leucocitaria se informa en porcentajes y los cinco tipos deben sumar 100 %. Un
dedo que resbala en NEUTRÓFILOS no deja ningún valor fuera de rango —cada celda sigue
siendo plausible por separado— así que ni las marcas ni los rangos de referencia lo ven:
lo único que delata el error es la suma.

El aviso **no bloquea** y **no se imprime**. Sale al guardar y al validar, que es donde
hay alguien mirando la pantalla. No puede ser en vivo porque también avisa cuando falta
cargar alguno de los cinco, y durante la captura faltan casi siempre.

Las reglas viven aquí, en código, y no en el catálogo (ADR-042): los cinco códigos salen
de la siembra base y son los mismos en todos los laboratorios, mientras que colgar la
regla de `ParameterGroup` obligaba a sacar la fórmula leucocitaria de SERIE BLANCA, y el
informe ordena por grupo —PLAQUETAS quedaría impresa antes de los leucocitos.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SumRule:
    """Parámetros que deben sumar `total` (± `tolerance`) dentro de un mismo examen."""

    name: str
    codes: tuple[str, ...]
    total: Decimal
    tolerance: Decimal
    unit: str = ""


SUM_RULES: tuple[SumRule, ...] = (
    SumRule(
        name="la fórmula leucocitaria",
        codes=("HEM_NEUTROFILOS", "HEM_LINFOCITOS", "HEM_EOSINOFILOS",
               "HEM_MONOCITOS", "HEM_BASOFILOS"),
        total=Decimal("100"), tolerance=Decimal("1"), unit="%",
    ),
)


def sum_warnings(sheet) -> list[str]:
    """Avisos de las sumas que no cuadran en la planilla. Nunca lanza: sólo informa."""
    warnings = []
    for block in sheet.blocks:
        # Un examen validado está congelado: el aviso ya no se puede atender sin
        # rectificar, y repetirlo en cada guardado de la orden sería ruido.
        if block.result.is_validated:
            continue
        rows = {row.parameter.code: row for row in block.rows}
        for rule in SUM_RULES:
            warning = _check(rule, rows=rows, test_name=block.item.test.name)
            if warning:
                warnings.append(warning)
    return warnings


def _check(rule: SumRule, *, rows: dict, test_name: str) -> str:
    present = [rows[code] for code in rule.codes if code in rows]
    # El laboratorio no tiene los cinco —los desactivó o los cambió—: la regla no es
    # suya y se calla. Es el punto ciego de tener la regla en código y no en el catálogo.
    if len(present) != len(rule.codes):
        return ""
    loaded = [row for row in present if row.parsed.numeric is not None]
    if not loaded:
        return ""  # todavía no se escribió nada de la fórmula
    unit = f" {rule.unit}" if rule.unit else ""
    missing = [row.parameter.name for row in present if row.parsed.numeric is None]
    if missing:
        return (f"{test_name}: falta cargar {_enumerated(missing)}, así que no se puede "
                f"comprobar que {rule.name} sume {_number(rule.total)}{unit}.")
    total = sum(row.parsed.numeric for row in loaded)
    if abs(total - rule.total) <= rule.tolerance:
        return ""
    return (f"{test_name}: {rule.name} suma {_number(total)}{unit} y debería sumar "
            f"{_number(rule.total)}{unit}. Revise los cinco porcentajes.")


def _number(value: Decimal) -> str:
    """Decimal en castellano y sin ceros de más: 100, 99,5."""
    return f"{value.normalize():f}".replace(".", ",")


def _enumerated(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " y " + names[-1]
