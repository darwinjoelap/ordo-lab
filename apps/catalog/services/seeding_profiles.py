"""Siembra de perfiles (Fase 08).

Composición leída de `Perfiles.xlsx` y `Formato_de_resultados - Angelus.xlsx` (una hoja
por perfil), laboratorio de referencia (ADR-018). Ajustes de Ordo Lab marcados en
`description` con "Agregado por Ordo Lab" (ADR-019).

Idempotente y no destructiva: si el perfil ya existe, **no** se toca su composición (el
tenant puede haberla editado). Sólo se crea lo que falta.
"""
from apps.catalog.models import Profile
from apps.catalog.selectors.catalog_queries import tests_by_codes
from apps.catalog.services.profiles import create_profile
from apps.catalog.services.seeding_base_catalog import seed_base_catalog
from apps.core.exceptions import ApplicationError

HC = "HEM_COMP"
LIPIDOS = ["COLESTEROL_TOTAL", "TRIGLICERIDOS", "HDL", "LDL_VLDL"]

# (código, nombre, exámenes en orden de impresión, descripción / origen)
PROFILES: list[tuple[str, str, list[str], str]] = [
    ("PERFIL_20", "PERFIL 20", [
        HC, "VSG", "GLICEMIA", "UREA", "CREATININA", "ACIDO_URICO", "CALCIO", "FOSFORO",
        *LIPIDOS, "INDICES_CASTELLI", "PROTEINAS_TOTALES", "BILIRRUBINAS", "TGO", "TGP",
    ], "Hoja 'PERFIL 20.ofi'."),
    ("PERFIL_BASICO", "PERFIL BÁSICO", [
        HC, "VSG", "GLICEMIA", "UREA", "CREATININA", "COLESTEROL_TOTAL", "TRIGLICERIDOS",
        "ACIDO_URICO",
    ], "Hoja 'P. BÁSICO' (la fila de VSG aparece sin rótulo en la hoja)."),
    ("PERFIL_LIPIDICO", "PERFIL LIPÍDICO", [*LIPIDOS, "INDICES_CASTELLI"],
     "Hoja 'P. LIPÍDICO'."),
    ("PERFIL_HEPATICO", "PERFIL HEPÁTICO", [
        HC, "PT", "PTT", "PROTEINAS_TOTALES", "BILIRRUBINAS", "TGO", "TGP", "ALP", "GGT",
        "LDH",
    ], "Hoja 'P. HEPÁTICO' (incluye hematología y coagulación)."),
    ("PERFIL_RENAL", "PERFIL RENAL", [
        HC, "GLICEMIA", "UREA", "CREATININA", "ACIDO_URICO", "PROTEINAS_TOTALES", "URO",
    ], "Hoja 'P. RENAL.ofi'."),
    ("PERFIL_PREOPERATORIO", "PERFIL PRE-OPERATORIO", [
        HC, "PT", "PTT", "GLICEMIA", "UREA", "CREATININA", "VDRL", "HIV", "GRUPO_SANGUINEO",
    ], "Hoja 'P. PRE-OPERAT'."),
    ("PERFIL_PRECLAMPTICO", "PERFIL PRECLÁMPTICO", [
        HC, "PT", "PTT", "FIBRINOGENO", "GLICEMIA", "UREA", "CREATININA",
        "COLESTEROL_TOTAL", "TRIGLICERIDOS", "ACIDO_URICO", "PROTEINAS_TOTALES", "TGO",
        "TGP", "LDH", "URO",
    ], "Hoja 'P. PRECLAMPTICO'. Agregado por Ordo Lab: UROANÁLISIS (la proteinuria es "
       "criterio diagnóstico de preeclampsia y la hoja no lo incluye)."),
    ("PERFIL_PEDIATRICO", "PERFIL PEDIÁTRICO", [HC, "VSG", "PCR"],
     "Hoja 'P. PEDIÁTRICO'. Los rangos pediátricos/neonatales siguen sin confirmar."),
    ("PERFIL_GLICEMICO", "PERFIL GLICÉMICO (POST-PRANDIAL)", [
        "GLICEMIA", "GLICEMIA_PP", "INSULINA_BASAL", "INSULINA_PP", "HBA1C", "HOMA_IR",
    ], "Hoja 'P. GLICÉMICO', variante post-prandial (2 horas)."),
    ("PERFIL_GLICEMICO_CARGA", "PERFIL GLICÉMICO (POST-CARGA 75 g)", [
        "GLICEMIA", "GLICEMIA_POST_CARGA", "INSULINA_BASAL", "INSULINA_POST_CARGA", "HBA1C",
        "HOMA_IR",
    ], "Hoja 'P. GLICÉMICO', variante post-carga de 75 g (la hoja trae ambas)."),
    ("ORINA_HECES", "ORINA + HECES", ["URO", "COPRO"], "Hoja 'ORINA+HECES.ofi'."),
    ("HC_COAG", "HEMATOLOGÍA + COAGULACIÓN", [HC, "PT", "PTT", "FIBRINOGENO"],
     "Hoja 'HC+COAG'."),
    ("HIV_VDRL", "HIV + VDRL", ["VDRL", "HIV"], "Hoja 'HIV+VDRL'."),
    ("HC_ORINA", "HEMATOLOGÍA + ORINA", [HC, "URO"], "Hoja 'HC+ORINA'."),
    ("PERFIL_PRENATAL", "PERFIL PRENATAL", [
        HC, "GRUPO_SANGUINEO", "GLICEMIA", "URO", "VDRL", "HIV", "HEPATITIS_B_HBSAG", "TORCH",
    ], "Agregado por Ordo Lab: control prenatal habitual; no existe en las hojas."),
]

# Los perfiles que corresponden a hojas de los Excel (criterio de salida de la Fase 08).
PROFILE_CODES_HOJAS: tuple[str, ...] = tuple(
    code for code, *_rest, description in PROFILES if description.startswith("Hoja")
)


def seed_profiles() -> list[Profile]:
    """Siembra el catálogo base (si falta) y los perfiles. Idempotente y no destructiva."""
    seed_base_catalog()
    all_codes = {code for _c, _n, codes, _d in PROFILES for code in codes}
    tests = tests_by_codes(codes=all_codes)
    missing = sorted(all_codes - tests.keys())
    if missing:
        raise ApplicationError(
            "Faltan exámenes para sembrar perfiles (¿corrió seed_uroanalisis?): "
            + ", ".join(missing)
        )

    profiles = []
    for order_index, (code, name, codes, description) in enumerate(PROFILES, start=1):
        existing = Profile.objects.filter(code=code).first()
        if existing:
            profiles.append(existing)
            continue
        profiles.append(
            create_profile(
                code=code, name=name, description=description, order_index=order_index,
                tests=[tests[c] for c in codes],
            )
        )
    return profiles
