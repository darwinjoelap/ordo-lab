"""Catálogo base de exámenes (Fase 08) — fuente única de la siembra de todo lo que no es
Uroanálisis (éste sigue en `services/seeding.py`, Fase 05).

Origen: las hojas `Formato_de_resultados - Angelus.xlsx` y `Perfiles.xlsx` (laboratorio de
referencia, ADR-018), leídas celda por celda — nombres, unidades, rangos y fórmulas. Cada
analito ordenable es un `Test` propio para que los perfiles puedan agruparlos (ADR-019).

**Códigos de parámetro estables:** los de las Fases 06/07 (`QUIM_*`, `LIP_*`, `COAG_*`) no
cambian aunque cambie el examen que los contiene, así que fórmulas y rangos siguen
válidos. Los exámenes agregados de las Fases 06/07 (`QUIM`, `PERFIL_LIPIDICO`, `COAGUL`)
se vacían (sus parámetros se mudan a los exámenes individuales) y se desactivan.

Marcas en `display_text`:
- "(PENDIENTE DE CONFIRMAR)": las hojas traen valores contradictorios; se sembró uno.
- "(NO CONFIRMADO)": ilustrativo, sin respaldo en las hojas.
- "(PROPUESTO)": agregado por Ordo Lab con criterio clínico estándar (ADR-018).
Ninguno de esos rangos debe usarse en un informe real sin que el laboratorio lo revise.

Idempotente: todo por `get_or_create` con claves naturales. No sobreescribe lo que el
tenant haya editado, salvo mudar parámetros que sigan colgando de un examen agregado viejo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from apps.catalog.models import (
    CodedOption,
    CodedOptionSet,
    Method,
    Parameter,
    ParameterGroup,
    ReferenceRange,
    Section,
    Test,
    Unit,
)
from apps.catalog.services.formula_validation import (
    set_parameter_formula,
    sync_parameter_dependencies,
)
from apps.catalog.services.seeding import _get_or_create_option_set

D = Decimal
EDAD_MAXIMA_DIAS = 54750
LEGACY_AGGREGATE_TESTS = ("QUIM", "PERFIL_LIPIDICO", "COAGUL")

VT = Parameter.ValueType
RT = ReferenceRange.RangeType
SEX = ReferenceRange.Sex
ST = Test.SampleType


# --------------------------------------------------------------------------- estructura
@dataclass(frozen=True)
class R:
    """Rango de referencia a sembrar."""

    type: str
    text: str
    low: Decimal | None = None
    high: Decimal | None = None
    center: Decimal | None = None
    tolerance: Decimal | None = None
    sex: str = SEX.ANY
    age_min: int = 0
    age_max: int = EDAD_MAXIMA_DIAS
    condition: str = ReferenceRange.Condition.NINGUNA
    expected: str = ""  # valor de la CodedOption esperada (QUALITATIVE)
    bands: list | None = None
    priority: int = 0


@dataclass(frozen=True)
class P:
    """Parámetro a sembrar."""

    code: str
    name: str
    vt: str = VT.NUMERIC
    unit: str = ""
    dec: int = 2
    options: str = ""  # código del CodedOptionSet
    formula: str = ""
    group: str = ""
    optional: bool = False
    ranges: tuple[R, ...] = ()


@dataclass(frozen=True)
class T:
    """Examen a sembrar."""

    code: str
    name: str
    section: str
    sample: str
    params: tuple[P, ...]
    method: str = ""
    fasting: bool = False
    anthropometry: bool = False
    groups: tuple[str, ...] = field(default_factory=tuple)


def closed(text, low, high, **kw) -> R:
    return R(RT.CLOSED, text, low=D(low), high=D(high), **kw)


def upper(text, high, **kw) -> R:
    return R(RT.UPPER_BOUND, text, high=D(high), **kw)


def lower(text, low, **kw) -> R:
    return R(RT.LOWER_BOUND, text, low=D(low), **kw)


def expects(value: str, text: str | None = None) -> R:
    return R(RT.QUALITATIVE, text or value, expected=value)


# --------------------------------------------------------------------------- catálogos
SECTIONS = {
    "HEMATOLOGIA": ("HEMATOLOGÍA", 10),
    "QUIMICA_SANGUINEA": ("QUÍMICA SANGUÍNEA", 20),
    "HORMONAS": ("HORMONAS Y PRUEBAS ESPECIALES", 25),
    "ORINA": ("ORINA", 30),
    "HECES": ("HECES", 35),
    "COAGULACION": ("COAGULACIÓN", 40),
    "SEROLOGIA": ("SEROLOGÍA", 50),
}

METHODS = {
    "LATEX": "Aglutinación látex semicuantitativo",
    "ICR_CUALI": "Inmunocromatografía cualitativa",
    "ICR_SEMI": "Inmunocromatografía semicuantitativa",
    "FLOCULACION": "Floculación",
    "JAFFE": "Colorimétrico Jaffé modificado",
}

OPTION_SETS: dict[str, tuple[str, list[dict]]] = {
    "NEG_POS": ("Negativo / positivo", [
        {"value": "NEGATIVO", "ordinal": 0},
        {"value": "POSITIVO", "ordinal": 1, "is_pathological": True},
    ]),
    "REACTIVIDAD": ("Reactividad", [
        {"value": "NO REACTIVO", "ordinal": 0},
        {"value": "REACTIVO", "ordinal": 1, "is_pathological": True},
    ]),
    "GRUPO_ABO": ("Grupo sanguíneo ABO", [
        {"value": "A", "ordinal": 0}, {"value": "B", "ordinal": 1},
        {"value": "AB", "ordinal": 2}, {"value": "O", "ordinal": 3},
    ]),
    "FACTOR_RH": ("Factor Rh", [
        {"value": "POSITIVO", "ordinal": 0}, {"value": "NEGATIVO", "ordinal": 1},
    ]),
    "TITULO_PCR": ("PCR — título (látex semicuantitativo)", [
        {"value": "NEGATIVO: Menor a 6,0 mg/L", "ordinal": 0},
        *[
            {
                "value": f"POSITIVO: 1/{d} = {v} mg/L", "ordinal": i,
                "numeric_equivalent": D(str(v).replace(",", ".")), "is_pathological": True,
            }
            for i, (d, v) in enumerate(
                [(1, "6,0"), (2, 12), (4, 24), (8, 48), (16, 96), (32, 192), (64, 384),
                 (128, 768), (256, 1536)],
                start=1,
            )
        ],
    ]),
    "TITULO_VDRL": ("VDRL — título (floculación)", [
        {"value": "NO REACTIVO", "ordinal": 0},
        *[
            {"value": f"REACTIVO: {d} Dils", "ordinal": i, "numeric_equivalent": D(d),
             "is_pathological": True}
            for i, d in enumerate([2, 4, 8, 16, 32, 64, 128, 256], start=1)
        ],
    ]),
    "COLOR_HECES": ("Color de heces", [
        {"value": v, "ordinal": i, "is_pathological": v in ("ROJO", "NEGRO")}
        for i, v in enumerate(["MARRÓN", "AMARILLO", "VERDE", "ROJO", "NEGRO"])
    ]),
    "CONSISTENCIA_HECES": ("Consistencia de heces", [
        {"value": v, "ordinal": i} for i, v in enumerate(["BLANDA", "DURA", "LÍQUIDA"])
    ]),
    "ASPECTO_HECES": ("Aspecto de heces", [
        {"value": v, "ordinal": i} for i, v in enumerate(["HETEROGÉNEO", "HOMOGÉNEO"])
    ]),
    "OLOR_HECES": ("Olor de heces", [
        {"value": v, "ordinal": i} for i, v in enumerate(["FECAL", "FÉTIDO"])
    ]),
    "REACCION_HECES": ("Reacción de heces", [
        {"value": v, "ordinal": i} for i, v in enumerate(["ÁCIDA", "ALCALINA"])
    ]),
    "PRESENCIA": ("Presencia (plural)", [
        {"value": "AUSENTES", "ordinal": 0}, {"value": "PRESENTES", "ordinal": 1},
    ]),
    "PRESENCIA_SING": ("Presencia (singular)", [
        {"value": "AUSENTE", "ordinal": 0},
        {"value": "PRESENTE", "ordinal": 1, "is_pathological": True},
    ]),
    "ABUNDANCIA_MASC": ("Abundancia (masculino singular)", [
        {"value": v, "ordinal": i, "is_pathological": i >= 2}
        for i, v in enumerate(["AUSENTE", "ESCASO", "MODERADO", "ABUNDANTE"])
    ]),
    "ABUNDANCIA": ("Abundancia (sedimento)", [
        {"value": v, "ordinal": i, "is_pathological": i >= 2}
        for i, v in enumerate(["AUSENTES", "ESCASAS", "MODERADAS", "ABUNDANTES"])
    ]),
    "MICROBIOTA": ("Microbiota bacteriana", [
        {"value": "NORMAL", "ordinal": 0},
        {"value": "AUMENTADA", "ordinal": 1, "is_pathological": True},
    ]),
    "PARASITOS": ("Hallazgos parasitarios", [
        {"value": v, "ordinal": i, "is_pathological": i > 0}
        for i, v in enumerate([
            "NO SE OBSERVARON FORMAS PARASITARIAS.",
            "Blastocystis spp. forma vacuolar.",
            "Blastocystis spp. forma granular.",
            "QUISTES DE Giardia intestinalis.",
            "QUISTES DE Entamoeba histolytica/E. dispar.",
            "QUISTES DE Entamoeba coli.",
            "QUISTES DE Endolimax nana.",
            "QUISTES Y TROFOZOÍTOS DE Giardia intestinalis.",
            "QUISTES Y TROFOZOÍTOS DE Entamoeba histolytica/E. dispar.",
            "QUISTES Y TROFOZOÍTOS DE Entamoeba coli.",
            "QUISTES Y TROFOZOÍTOS DE Endolimax nana.",
            "HUEVOS DE Enterobius vermicularis.",
            "HUEVOS DE Ascaris lumbricoides.",
            "HUEVOS DE Anquilostomídeos.",
            "HUEVOS Y LARVAS DE Enterobius vermicularis.",
            "HUEVOS Y LARVAS DE Ascaris lumbricoides.",
            "LARVAS DE Strongyloides stercoralis.",
        ])
    ]),
}

PENDIENTE = " (PENDIENTE DE CONFIRMAR)"

HOMA_BANDS = [
    {"max": 2.0, "text": "NORMAL"},
    {"min": 2.0, "text": "ALERTA DE RESISTENCIA A LA INSULINA"},
    {"min": 2.5, "text": "RESISTENCIA A LA INSULINA"},
    {"min": 4.0, "text": "RESISTENCIA A LA INSULINA MARCADA"},
]
HBA1C_BANDS = [
    {"max": 5.7, "text": "NORMAL"},
    {"min": 5.7, "text": "PREDIABETES"},
    {"min": 6.5, "text": "DIABETES"},
]
PROCALCITONINA_BANDS = [
    {"max": 0.5, "text": "Posible infección localizada."},
    {"min": 0.5, "text": "Posible infección sistémica."},
    {"min": 2.0, "text": "Probable infección sistémica (sepsis)."},
    {"min": 10.0, "text": "Alta probabilidad de shock séptico."},
]


def _qualitative_tests(specs, *, section, method, options="NEG_POS", expected="NEGATIVO"):
    """Exámenes de un solo parámetro cualitativo (serología rápida, coprología)."""
    return [
        T(code, name, section, ST.SUERO if section == "SEROLOGIA" else ST.HECES,
          (P(param, name, VT.QUALITATIVE, options=options, ranges=(expects(expected),)),),
          method=method)
        for code, param, name in specs
    ]


def _paired_igg_igm(prefix: str, label: str) -> tuple[P, P]:
    return (
        P(f"{prefix}_IGG", f"{label} IgG", VT.QUALITATIVE, options="NEG_POS",
          ranges=(expects("NEGATIVO"),)),
        P(f"{prefix}_IGM", f"{label} IgM", VT.QUALITATIVE, options="NEG_POS",
          ranges=(expects("NEGATIVO"),)),
    )


# --------------------------------------------------------------------------- exámenes
TESTS: list[T] = [
    # ---------------------------------------------------------------- Hematología
    T("HEM_COMP", "HEMATOLOGÍA COMPLETA", "HEMATOLOGIA", ST.SANGRE_TOTAL,
      groups=("SERIE ROJA", "SERIE BLANCA"), params=(
        P("HEM_HEMOGLOBINA", "HEMOGLOBINA", unit="g/dL", dec=1, group="SERIE ROJA", ranges=(
            closed("13,0 - 15,0 g/dL", "13.0", "15.0", sex=SEX.M),
            closed("12,0 - 16,0 g/dL", "12.0", "16.0", sex=SEX.F),
        )),
        P("HEM_HEMATOCRITO", "HEMATOCRITO", unit="%", dec=0, group="SERIE ROJA",
          ranges=(closed("41 - 50 %", "41", "50"),)),
        P("HEM_CHCM", "CHCM", VT.NUMERIC_CALCULATED, unit="%", dec=1, group="SERIE ROJA",
          formula="{HEM_HEMOGLOBINA} / {HEM_HEMATOCRITO} * 100",
          ranges=(closed("31 - 33 %", "31", "33"),)),
        P("HEM_GLOBULOS_BLANCOS", "GLÓBULOS BLANCOS", unit="/mm3", dec=0,
          group="SERIE BLANCA", ranges=(
              closed("9.000 - 30.000/mm3 (NO CONFIRMADO)", "9000", "30000",
                     age_min=0, age_max=28, priority=1),
              closed("4.500 - 10.000/mm3", "4500", "10000", age_min=29),
          )),
        P("HEM_NEUTROFILOS", "NEUTRÓFILOS", unit="%", dec=0, group="SERIE BLANCA",
          ranges=(closed("50 - 70 %", "50", "70"),)),
        P("HEM_LINFOCITOS", "LINFOCITOS", unit="%", dec=0, group="SERIE BLANCA",
          ranges=(closed("20 - 40 %", "20", "40"),)),
        P("HEM_EOSINOFILOS", "EOSINÓFILOS", unit="%", dec=0, group="SERIE BLANCA",
          ranges=(closed("0 - 2 %", "0", "2"),)),
        # Sin rango en las hojas (celda vacía): el informe la imprime vacía.
        P("HEM_MONOCITOS", "MONOCITOS", unit="%", dec=0, group="SERIE BLANCA"),
        P("HEM_BASOFILOS", "BASÓFILOS", unit="%", dec=0, group="SERIE BLANCA"),
        P("HEM_PLAQUETAS", "PLAQUETAS", unit="/mm3", dec=0, group="SERIE BLANCA",
          ranges=(closed("150.000 - 450.000/mm3", "150000", "450000"),)),
    )),
    T("VSG", "VELOCIDAD DE SEDIMENTACIÓN GLOBULAR", "HEMATOLOGIA", ST.SANGRE_TOTAL,
      params=(
          P("HEM_VSG", "VSG", unit="mm/h", dec=0, ranges=(closed("0 - 15 mm/h", "0", "15"),)),
      )),
    T("GRUPO_SANGUINEO", "GRUPO SANGUÍNEO (TIPIAJE)", "HEMATOLOGIA", ST.SANGRE_TOTAL,
      params=(
          P("GS_GRUPO", "GRUPO SANGUÍNEO", VT.CODED, options="GRUPO_ABO"),
          P("GS_FACTOR_RH", "FACTOR Rh", VT.CODED, options="FACTOR_RH"),
      )),
    T("HBA1C", "HEMOGLOBINA GLICADA (HbA1c)", "HORMONAS", ST.SANGRE_TOTAL,
      params=(
          P("ESP_HBA1C", "HEMOGLOBINA GLICADA (HbA1c)", unit="%", dec=1, ranges=(
              R(RT.INTERPRETIVE, "NORMAL: MENOR A 5,7 % (PROPUESTO, criterios ADA)",
                bands=HBA1C_BANDS),
          )),
      )),
    # ---------------------------------------------------------------- Química sanguínea
    T("GLICEMIA", "GLICEMIA", "QUIMICA_SANGUINEA", ST.SUERO, fasting=True, params=(
        P("QUIM_GLICEMIA", "GLICEMIA", unit="mg/dL", dec=0,
          ranges=(closed("70 - 100 mg/dL" + PENDIENTE, "70", "100"),)),
    )),
    T("GLICEMIA_PP", "GLICEMIA POST-PRANDIAL (2 horas)", "QUIMICA_SANGUINEA", ST.SUERO,
      params=(
          P("QUIM_GLICEMIA_PP", "GLICEMIA POST-PRANDIAL (2 horas)", unit="mg/dL", dec=0,
            ranges=(upper("MENOR A 140 mg/dL", "140"),)),
      )),
    T("GLICEMIA_POST_CARGA", "GLICEMIA POST-CARGA 75 g", "QUIMICA_SANGUINEA", ST.SUERO,
      params=(
          P("QUIM_GLICEMIA_POST_CARGA", "GLICEMIA POST-CARGA 75 g", unit="mg/dL", dec=0,
            ranges=(upper("MENOR A 140 mg/dL", "140"),)),
      )),
    T("UREA", "ÚREA", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_UREA", "ÚREA", unit="mg/dL", dec=0,
          ranges=(closed("20 - 45 mg/dL" + PENDIENTE, "20", "45"),)),
    )),
    T("CREATININA", "CREATININA", "QUIMICA_SANGUINEA", ST.SUERO, method="JAFFE", params=(
        P("QUIM_CREATININA", "CREATININA", unit="mg/dL", dec=2,
          ranges=(closed("0,70 - 1,20 mg/dL" + PENDIENTE, "0.70", "1.20"),)),
    )),
    T("ACIDO_URICO", "ÁCIDO ÚRICO", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_ACIDO_URICO", "ÁCIDO ÚRICO", unit="mg/dL", dec=1,
          ranges=(closed("3,0 - 7,0 mg/dL" + PENDIENTE, "3.0", "7.0"),)),
    )),
    T("COLESTEROL_TOTAL", "COLESTEROL TOTAL", "QUIMICA_SANGUINEA", ST.SUERO, fasting=True,
      params=(
          # Condición NINGUNA (antes AYUNO, ADR-021): el ayuno es requisito del examen
          # (requires_fasting), no un rango distinto.
          P("LIP_COLESTEROL_TOTAL", "COLESTEROL TOTAL", unit="mg/dL", dec=0, ranges=(
              upper("MENOR A 200 mg/dL", "200"),
          )),
      )),
    T("TRIGLICERIDOS", "TRIGLICÉRIDOS", "QUIMICA_SANGUINEA", ST.SUERO, fasting=True,
      params=(
          P("LIP_TRIGLICERIDOS", "TRIGLICÉRIDOS", unit="mg/dL", dec=0, ranges=(
              upper("MENOR A 150 mg/dL", "150"),
          )),
      )),
    T("HDL", "HDL-c", "QUIMICA_SANGUINEA", ST.SUERO, fasting=True, params=(
        P("LIP_HDL", "HDL-c", unit="mg/dL", dec=1, ranges=(
            lower("MAYOR 40 mg/dL", "40"),
        )),
    )),
    T("LDL_VLDL", "LDL-c y VLDL-c (Friedewald)", "QUIMICA_SANGUINEA", ST.SUERO, fasting=True,
      params=(
          P("LIP_LDL", "LDL-c", VT.NUMERIC_CALCULATED, unit="mg/dL", dec=1,
            formula="{LIP_COLESTEROL_TOTAL} - {LIP_HDL} - {LIP_VLDL}",
            ranges=(upper("MENOR A 100 mg/dL", "100"),)),
          P("LIP_VLDL", "VLDL-c", VT.NUMERIC_CALCULATED, unit="mg/dL", dec=1,
            formula="{LIP_TRIGLICERIDOS} / 5", ranges=(upper("MENOR A 30 mg/dL", "30"),)),
      )),
    T("INDICES_CASTELLI", "ÍNDICES DE RIESGO CARDIOVASCULAR", "QUIMICA_SANGUINEA", ST.SUERO,
      groups=("ÍNDICE DE CASTELLI - I", "ÍNDICE DE CASTELLI - II"), params=(
          P("LIP_CASTELLI_I", "COLESTEROL TOTAL / HDL-c", VT.NUMERIC_CALCULATED, dec=2,
            group="ÍNDICE DE CASTELLI - I", formula="{LIP_COLESTEROL_TOTAL} / {LIP_HDL}",
            ranges=(upper("MENOR A 4,5", "4.5"),)),
          P("LIP_CASTELLI_II", "LDL-c/HDL-c", VT.NUMERIC_CALCULATED, dec=2,
            group="ÍNDICE DE CASTELLI - II", formula="{LIP_LDL} / {LIP_HDL}",
            ranges=(upper("MENOR A 2,5", "2.5"),)),
      )),
    T("PROTEINAS_TOTALES", "PROTEÍNAS TOTALES Y FRACCIONADAS", "QUIMICA_SANGUINEA",
      ST.SUERO, params=(
          P("QUIM_PROTEINAS_TOTALES", "PROTEÍNAS TOTALES", unit="g/dL", dec=1,
            ranges=(closed("6,0 - 8,0 g/dL", "6.0", "8.0"),)),
          P("QUIM_ALBUMINA", "ALBÚMINA", unit="g/dL", dec=1,
            ranges=(closed("3,5 - 5,0 g/dL", "3.5", "5.0"),)),
          P("QUIM_GLOBULINAS", "GLOBULINAS", VT.NUMERIC_CALCULATED, unit="g/dL", dec=1,
            formula="{QUIM_PROTEINAS_TOTALES} - {QUIM_ALBUMINA}",
            ranges=(closed("2,0 - 3,5 g/dL", "2.0", "3.5"),)),
          P("QUIM_REL_ALB_GLO", "REL. ALB/GLO", VT.NUMERIC_CALCULATED, dec=2,
            formula="{QUIM_ALBUMINA} / {QUIM_GLOBULINAS}",
            ranges=(closed("1,2 - 2,2", "1.2", "2.2"),)),
      )),
    T("BILIRRUBINAS", "BILIRRUBINA TOTAL Y FRACCIONADA", "QUIMICA_SANGUINEA", ST.SUERO,
      params=(
          P("QUIM_BILIRRUBINA_TOTAL", "BILIRRUBINA TOTAL", unit="mg/dL", dec=2,
            ranges=(closed("0,10 - 1,20 mg/dL" + PENDIENTE, "0.10", "1.20"),)),
          P("QUIM_BILIRRUBINA_DIRECTA", "BILIRRUBINA DIRECTA", unit="mg/dL", dec=2,
            ranges=(closed("0,05 - 0,30 mg/dL" + PENDIENTE, "0.05", "0.30"),)),
          P("QUIM_BILIRRUBINA_INDIRECTA", "BILIRRUBINA INDIRECTA", VT.NUMERIC_CALCULATED,
            unit="mg/dL", dec=2,
            formula="{QUIM_BILIRRUBINA_TOTAL} - {QUIM_BILIRRUBINA_DIRECTA}",
            ranges=(closed("0,20 - 0,80 mg/dL", "0.20", "0.80"),)),
      )),
    T("TGO", "TGO (ASAT)", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_TGO", "TGO (ASAT)", unit="U/L", dec=0,
          ranges=(upper("MENOR A 40 U/L" + PENDIENTE, "40"),)),
    )),
    T("TGP", "TGP (ALAT)", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_TGP", "TGP (ALAT)", unit="U/L", dec=0,
          ranges=(upper("MENOR A 40 U/L" + PENDIENTE, "40"),)),
    )),
    T("ALP", "ALP (FOSFATASA ALCALINA)", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_ALP", "ALP (FOSFATASA ALCALINA)", unit="U/L", dec=0,
          ranges=(upper("MENOR A 120 U/L", "120"),)),
    )),
    T("GGT", "GGT (GAMMA-GLUTAMIL TRANSFERASA)", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_GGT", "GGT (GAMMA-GLUTAMIL TRANSFERASA)", unit="U/L", dec=0,
          ranges=(upper("MENOR A 40 U/L", "40"),)),
    )),
    T("LDH", "LDH (LACTATO DESHIDROGENASA)", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_LDH", "LDH (LACTATO DESHIDROGENASA)", unit="IU/L", dec=0, ranges=(
            closed("HOMBRE: 80 - 285 IU/L" + PENDIENTE, "80", "285", sex=SEX.M),
            closed("MUJERES: 103 - 227 IU/L" + PENDIENTE, "103", "227", sex=SEX.F),
        )),
    )),
    T("AMILASA", "AMILASA", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_AMILASA", "AMILASA", unit="U/L", dec=0, optional=True),
    )),
    T("LIPASA", "LIPASA", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_LIPASA", "LIPASA", unit="U/L", dec=0, optional=True),
    )),
    T("ELECTROLITOS", "ELECTROLITOS SÉRICOS", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_SODIO", "SODIO (Na+)", unit="mEq/L", dec=1,
          ranges=(closed("135 - 155 mEq/L", "135", "155"),)),
        P("QUIM_POTASIO", "POTASIO (K+)", unit="mEq/L", dec=1,
          ranges=(closed("3,4 - 5,3 mEq/L", "3.4", "5.3"),)),
        P("QUIM_CLORO", "CLORO (Cl-)", unit="mEq/L", dec=1,
          ranges=(closed("98 - 106 mEq/L", "98", "106"),)),
    )),
    T("CALCIO", "CALCIO", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_CALCIO", "CALCIO (Ca++)", unit="mg/dL", dec=1,
          ranges=(closed("8,6 - 10,0 mg/dL", "8.6", "10.0"),)),
    )),
    T("FOSFORO", "FÓSFORO", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        P("QUIM_FOSFORO", "FÓSFORO (P)", unit="mg/dL", dec=1,
          ranges=(closed("2,9 - 4,7 mg/dL", "2.9", "4.7"),)),
    )),
    T("MAGNESIO", "MAGNESIO", "QUIMICA_SANGUINEA", ST.SUERO, params=(
        # La hoja imprime "-  mg/dL": sin rango.
        P("QUIM_MAGNESIO", "MAGNESIO (Mg++)", unit="mg/dL", dec=1),
    )),
    T("DEPURACION", "DEPURACIÓN DE CREATININA EN ORINA", "QUIMICA_SANGUINEA",
      ST.ORINA_24H, method="JAFFE", anthropometry=True, params=(
          P("DEP_CREAT_SERICA", "CREATININA SÉRICA", unit="mg/dL", dec=2,
            ranges=(closed("0,60 - 1,40 mg/dL", "0.60", "1.40"),)),
          P("DEP_CREAT_ORINA", "CREATININA EN ORINA", unit="mg/dL", dec=1),
          P("DEP_DEPURACION_CORREGIDA", "DEPURACIÓN DE CREATININA CORREGIDA",
            VT.NUMERIC_CALCULATED, unit="mL/min", dec=2,
            formula="{DEP_DEPURACION_SIN_CORR} * 1.73 / {DEP_SUPERFICIE_CORPORAL}", ranges=(
                closed("Hombres: 70 - 140 mL/min", "70", "140", sex=SEX.M),
                closed("Mujeres: 70 - 130 mL/min", "70", "130", sex=SEX.F),
            )),
          P("DEP_DEPURACION_SIN_CORR", "DEPURACIÓN DE CREATININA SIN CORREGIR",
            VT.NUMERIC_CALCULATED, unit="mL/min", dec=2,
            formula="({DEP_CREAT_ORINA} * {@volumen_orina_24h}) / ({DEP_CREAT_SERICA} * 1440)"),
          # Mosteller: es la fórmula de la celda de la hoja DEPURACIÓN (ADR-017/019).
          P("DEP_SUPERFICIE_CORPORAL", "SUPERFICIE CORPORAL", VT.NUMERIC_CALCULATED,
            unit="m2", dec=4, formula="sqrt({@talla} * {@peso} / 3600)"),
          P("DEP_VOLUMEN_MINUTO", "VOLUMEN/MINUTO", VT.NUMERIC_CALCULATED, unit="mL/min",
            dec=2, formula="{@volumen_orina_24h} / 1440",
            ranges=(closed("0,4 – 1,7 mL/min", "0.4", "1.7"),)),
          P("DEP_CREAT_URINARIA_24H", "CREATININA URINARIA EN 24 HORAS",
            VT.NUMERIC_CALCULATED, unit="g/24h", dec=2,
            formula="{DEP_CREAT_ORINA} * {@volumen_orina_24h} / 100000",
            ranges=(closed("0,6 - 1,6 g/24 horas", "0.6", "1.6"),)),
      )),
    # ---------------------------------------------------------------- Hormonas
    T("INSULINA_BASAL", "INSULINA BASAL", "HORMONAS", ST.SUERO, fasting=True, params=(
        # La hoja dice "U/mL": la unidad clínica es µU/mL (ADR-019).
        P("HOR_INSULINA_BASAL", "INSULINA BASAL", unit="µU/mL", dec=1,
          ranges=(upper("MENOR A 10 µU/mL" + PENDIENTE, "10"),)),
    )),
    T("INSULINA_PP", "INSULINA POST-PRANDIAL (2 horas)", "HORMONAS", ST.SUERO, params=(
        P("HOR_INSULINA_PP", "INSULINA POST-PRANDIAL (2 horas)", unit="µU/mL", dec=1),
    )),
    T("INSULINA_POST_CARGA", "INSULINA POST-CARGA 75 g", "HORMONAS", ST.SUERO, params=(
        # La hoja imprime "40 - 230 U/mL": sin sembrar hasta confirmar (ADR-019).
        P("HOR_INSULINA_POST_CARGA", "INSULINA POST-CARGA 75 g", unit="µU/mL", dec=1),
    )),
    T("HOMA_IR", "ÍNDICE DE RESISTENCIA A LA INSULINA (HOMA-IR)", "HORMONAS", ST.SUERO,
      fasting=True, params=(
          P("HOR_HOMA_IR", "HOMA-IR", VT.NUMERIC_CALCULATED, dec=2,
            formula="{QUIM_GLICEMIA} * {HOR_INSULINA_BASAL} / 405", ranges=(
                R(RT.INTERPRETIVE, "NORMAL: MENOR A 2,0", bands=HOMA_BANDS),
            )),
      )),
    # ---------------------------------------------------------------- Coagulación
    T("PT", "TIEMPO DE PROTROMBINA (PT)", "COAGULACION", ST.PLASMA,
      params=(
          P("COAG_PT_PACIENTE", "PACIENTE", unit="seg", dec=1),
          P("COAG_PT_CONTROL", "CONTROL", unit="seg", dec=1),
          P("COAG_PT_RAZON", "RAZÓN", VT.NUMERIC_CALCULATED, dec=2,
            formula="{COAG_PT_PACIENTE} / {COAG_PT_CONTROL}",
            ranges=(closed("0,80 - 1,20", "0.80", "1.20"),)),
          P("COAG_INR", "INR", VT.NUMERIC_CALCULATED, dec=2,
            formula="{COAG_PT_RAZON} ** {@isi}",
            ranges=(closed("0,80 - 1,20", "0.80", "1.20"),)),
      )),
    T("PTT", "TIEMPO DE TROMBOPLASTINA PARCIAL (PTT)", "COAGULACION", ST.PLASMA,
      params=(
          P("COAG_PTT_PACIENTE", "PACIENTE", unit="seg", dec=1),
          P("COAG_PTT_CONTROL", "CONTROL", unit="seg", dec=1),
          P("COAG_PTT_DIFERENCIA", "DIFERENCIA", VT.NUMERIC_CALCULATED, unit="seg", dec=1,
            formula="{COAG_PTT_PACIENTE} - {COAG_PTT_CONTROL}", ranges=(
                R(RT.TOLERANCE, "± 6,0 segundos", center=D("0"), tolerance=D("6.0")),
            )),
      )),
    T("FIBRINOGENO", "FIBRINÓGENO", "COAGULACION", ST.PLASMA,
      params=(
          P("COAG_FIBRINOGENO", "FIBRINÓGENO", unit="mg/dL", dec=0,
            ranges=(closed("200 - 400 mg/dL", "200", "400"),)),
      )),
    # ---------------------------------------------------------------- Serología
    T("PCR", "PROTEÍNA C REACTIVA (PCR)", "SEROLOGIA", ST.SUERO, method="LATEX", params=(
        P("SERO_PCR", "PROTEÍNA C REACTIVA (PCR)", VT.TITER, options="TITULO_PCR", ranges=(
            expects("NEGATIVO: Menor a 6,0 mg/L", "Sensibilidad: Menor a 6,0 mg/L"),
        )),
    )),
    T("VDRL", "VDRL", "SEROLOGIA", ST.SUERO, method="FLOCULACION", params=(
        P("SERO_VDRL", "VDRL", VT.TITER, options="TITULO_VDRL",
          ranges=(expects("NO REACTIVO"),)),
    )),
    T("HIV", "HIV", "SEROLOGIA", ST.SUERO, method="ICR_CUALI", params=(
        P("SERO_HIV", "HIV", VT.QUALITATIVE, options="REACTIVIDAD",
          ranges=(expects("NO REACTIVO"),)),
    )),
    *_qualitative_tests([
        ("ASTO", "SERO_ASTO", "ANTI-ESTREPTOLISINA O (ASTO)"),
        ("RA_TEST", "SERO_RA_TEST", "ARTRITIS REUMATOIDE (RA-TEST)"),
    ], section="SEROLOGIA", method="LATEX"),
    *_qualitative_tests([
        ("HCG", "SERO_HCG", "PRUEBA DE EMBARAZO (HCG)"),
        ("FTA_ABS", "SERO_FTA_ABS", "FTA-Abs (SÍFILIS TEST)"),
        ("HEPATITIS_A_IGM", "SERO_HEP_A_IGM", "HEPATITIS A IgM (Test)"),
        ("HEPATITIS_B_HBSAG", "SERO_HBSAG", "HEPATITIS B Antígeno de superficie (Test)"),
        ("HEPATITIS_B_CORE", "SERO_HBCORE", "HEPATITIS B Antígeno CORE (Test)"),
        ("HEPATITIS_C", "SERO_HCV", "HEPATITIS C (Test)"),
    ], section="SEROLOGIA", method="ICR_CUALI"),
    T("DENGUE", "DENGUE IgG - IgM", "SEROLOGIA", ST.SUERO, method="ICR_CUALI",
      params=_paired_igg_igm("SERO_DENGUE", "DENGUE")),
    T("TORCH", "TORCH IgG - IgM", "SEROLOGIA", ST.SUERO, method="ICR_CUALI", params=(
        *_paired_igg_igm("SERO_TOXO", "TOXOPLASMOSIS"),
        *_paired_igg_igm("SERO_RUBEOLA", "RUBEOLA"),
        *_paired_igg_igm("SERO_CMV", "CITOMEGALOVIRUS"),
        *_paired_igg_igm("SERO_HSV12", "HERPES SIMPLEX I/II"),
    )),
    T("HERPES_II", "HERPES SIMPLEX II IgG - IgM", "SEROLOGIA", ST.SUERO, method="ICR_CUALI",
      params=_paired_igg_igm("SERO_HSV2", "HERPES SIMPLEX II")),
    T("PROCALCITONINA", "PROCALCITONINA", "SEROLOGIA", ST.SUERO, method="ICR_SEMI", params=(
        P("QUIM_PROCALCITONINA", "PROCALCITONINA", unit="ng/mL", dec=2, ranges=(
            R(RT.INTERPRETIVE, "Interpretación según banda (ver 'bands')",
              bands=PROCALCITONINA_BANDS),
        )),
    )),
    # ---------------------------------------------------------------- Heces
    T("COPRO", "EXAMEN DE HECES (COPROANÁLISIS)", "HECES", ST.HECES,
      groups=("EXAMEN MACROSCÓPICO", "EXAMEN MICROSCÓPICO"), params=(
          P("COPRO_COLOR", "COLOR", VT.CODED, options="COLOR_HECES",
            group="EXAMEN MACROSCÓPICO"),
          P("COPRO_CONSISTENCIA", "CONSISTENCIA", VT.CODED, options="CONSISTENCIA_HECES",
            group="EXAMEN MACROSCÓPICO"),
          P("COPRO_ASPECTO", "ASPECTO", VT.CODED, options="ASPECTO_HECES",
            group="EXAMEN MACROSCÓPICO"),
          P("COPRO_OLOR", "OLOR", VT.CODED, options="OLOR_HECES", group="EXAMEN MACROSCÓPICO"),
          P("COPRO_REACCION", "REACCIÓN", VT.CODED, options="REACCION_HECES",
            group="EXAMEN MACROSCÓPICO"),
          P("COPRO_RESTOS_ALIMENTICIOS", "RESTOS ALIMENTICIOS", VT.CODED,
            options="PRESENCIA", group="EXAMEN MACROSCÓPICO"),
          P("COPRO_SANGRE", "SANGRE", VT.QUALITATIVE, options="PRESENCIA_SING",
            group="EXAMEN MACROSCÓPICO", ranges=(expects("AUSENTE"),)),
          P("COPRO_MOCO", "MOCO", VT.SEMIQUANTITATIVE, options="ABUNDANCIA_MASC",
            group="EXAMEN MACROSCÓPICO"),
          P("COPRO_PARASITOS", "EN LA MUESTRA ANALIZADA SE OBSERVÓ", VT.MULTI_CATALOG,
            options="PARASITOS", group="EXAMEN MICROSCÓPICO"),
          P("COPRO_MICROBIOTA", "MICROBIOTA BACTERIANA", VT.CODED, options="MICROBIOTA",
            group="EXAMEN MICROSCÓPICO"),
          *[
              P(f"COPRO_{code}", label, VT.SEMIQUANTITATIVE, unit="P/C",
                options="ABUNDANCIA", group="EXAMEN MICROSCÓPICO")
              for code, label in [
                  ("LEUCOCITOS", "LEUCOCITOS"), ("HEMATIES", "HEMATÍES"),
                  ("LEVADURAS", "LEVADURAS"), ("BLASTOCONIDIAS", "BLASTOCONIDIAS"),
                  ("ALMIDON", "RESTOS DE ALMIDÓN"), ("GRASA", "GLÓBULOS DE GRASA"),
              ]
          ],
          P("COPRO_OTROS", "OTROS", VT.NARRATIVE, group="EXAMEN MICROSCÓPICO", optional=True),
      )),
    *_qualitative_tests([
        ("SANGRE_OCULTA", "HEC_SANGRE_OCULTA", "SANGRE OCULTA EN HECES"),
        ("H_PYLORI_HECES", "HEC_H_PYLORI", "Helicobacter pylori EN HECES"),
        ("ROTAVIRUS", "HEC_ROTAVIRUS", "ROTAVIRUS EN HECES"),
        ("ADENOVIRUS", "HEC_ADENOVIRUS", "ADENOVIRUS EN HECES"),
    ], section="HECES", method="ICR_CUALI"),
    T("LEUCOGRAMA_FECAL", "LEUCOGRAMA FECAL", "HECES", ST.HECES, params=(
        P("HEC_POLIMORFONUCLEARES", "POLIMORFONUCLEARES", unit="%", dec=0),
        P("HEC_MONONUCLEARES", "MONONUCLEARES", unit="%", dec=0),
    )),
]


# --------------------------------------------------------------------------- siembra
def _ensure_option_sets() -> dict[str, CodedOptionSet]:
    return {
        code: _get_or_create_option_set(code=code, name=name, options=options)
        for code, (name, options) in OPTION_SETS.items()
    }


def _ensure_test(spec: T, *, sections, methods) -> Test:
    test, _ = Test.objects.get_or_create(
        code=spec.code,
        defaults={
            "name": spec.name, "section": sections[spec.section], "sample_type": spec.sample,
            "method": methods.get(spec.method),
            "requires_fasting": spec.fasting, "requires_anthropometry": spec.anthropometry,
        },
    )
    return test


def _ensure_parameter(
    spec: P, *, test: Test, order_index: int, groups, units, option_sets
) -> Parameter:
    unit = None
    if spec.unit:
        unit = units.get(spec.unit) or Unit.objects.get_or_create(symbol=spec.unit)[0]
        units[spec.unit] = unit
    group = groups.get(spec.group) if spec.group else None
    parameter, created = Parameter.objects.get_or_create(
        code=spec.code,
        defaults={
            "test": test, "group": group, "name": spec.name, "value_type": spec.vt,
            "unit": unit, "decimals": spec.dec, "order_index": order_index,
            "option_set": option_sets.get(spec.options), "formula": spec.formula,
            "is_optional": spec.optional,
        },
    )
    # Mudanza desde los exámenes agregados de las Fases 06/07 (QUIM, PERFIL_LIPIDICO,
    # COAGUL). Sólo si todavía cuelga de uno de ellos: nunca pisa ediciones del tenant.
    if not created and parameter.test.code in LEGACY_AGGREGATE_TESTS:
        parameter.test = test
        parameter.group = group
        parameter.name = spec.name
        parameter.order_index = order_index
        parameter.decimals = spec.dec
        parameter.save(
            update_fields=["test", "group", "name", "order_index", "decimals", "updated_at"]
        )
    # Parámetros de la Fase 06 creados sin grupo: se completa el hueco, no se pisa nada.
    elif not created and group and parameter.group_id is None and parameter.test_id == test.id:
        parameter.group = group
        parameter.order_index = order_index
        parameter.save(update_fields=["group", "order_index", "updated_at"])
    return parameter


def _ensure_range(spec: R, *, parameter: Parameter, option_sets) -> ReferenceRange:
    expected = None
    if spec.expected:
        expected = CodedOption.objects.get(option_set=parameter.option_set, value=spec.expected)
    reference_range, _ = ReferenceRange.objects.get_or_create(
        parameter=parameter, sex=spec.sex, age_min_days=spec.age_min,
        age_max_days=spec.age_max, condition=spec.condition, range_type=spec.type,
        defaults={
            "display_text": spec.text, "low": spec.low, "high": spec.high,
            "center": spec.center, "tolerance": spec.tolerance, "expected_option": expected,
            "bands": spec.bands, "unit": parameter.unit, "priority": spec.priority,
        },
    )
    return reference_range


def _deactivate_empty_legacy_tests() -> None:
    for test in Test.objects.filter(code__in=LEGACY_AGGREGATE_TESTS, is_active=True):
        if not test.parameters.exists():
            test.is_active = False
            test.save(update_fields=["is_active", "updated_at"])


def seed_base_catalog() -> None:
    """Siembra/actualiza el catálogo base. Idempotente. Debe correr dentro del
    `schema_context()` del tenant."""
    sections = {
        code: Section.objects.get_or_create(
            code=code, defaults={"name": name, "order_index": order}
        )[0]
        for code, (name, order) in SECTIONS.items()
    }
    methods = {
        key: Method.objects.get_or_create(name=name)[0] for key, name in METHODS.items()
    }
    option_sets = _ensure_option_sets()
    units: dict[str, Unit] = {}

    calculated: list[tuple[Parameter, str]] = []
    ranges: list[tuple[Parameter, R]] = []
    for spec in TESTS:
        test = _ensure_test(spec, sections=sections, methods=methods)
        groups = {
            name: ParameterGroup.objects.get_or_create(
                test=test, name=name, defaults={"order_index": index}
            )[0]
            for index, name in enumerate(spec.groups, start=1)
        }
        for index, param_spec in enumerate(spec.params, start=1):
            parameter = _ensure_parameter(
                param_spec, test=test, order_index=index, groups=groups, units=units,
                option_sets=option_sets,
            )
            if param_spec.formula:
                calculated.append((parameter, param_spec.formula))
            ranges.extend((parameter, r) for r in param_spec.ranges)

    # Las fórmulas se validan cuando ya existen todos los parámetros que referencian.
    for parameter, formula in calculated:
        # Si el tenant cambió la fórmula, se respeta; si no, se valida y se enlaza.
        if parameter.formula == formula:
            set_parameter_formula(parameter=parameter, formula=formula)
    for parameter, range_spec in ranges:
        _ensure_range(range_spec, parameter=parameter, option_sets=option_sets)

    for parameter in Parameter.objects.filter(value_type=VT.NUMERIC_CALCULATED).exclude(
        formula=""
    ):
        sync_parameter_dependencies(parameter=parameter)
    _deactivate_empty_legacy_tests()
