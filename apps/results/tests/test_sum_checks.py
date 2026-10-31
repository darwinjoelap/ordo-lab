"""Aviso de la suma de la fórmula leucocitaria (ADR-042).

Los cinco porcentajes deben sumar 100 ± 1. El aviso avisa; no bloquea ni se imprime.
"""
from apps.catalog.models import Parameter
from apps.results.models import Result, ResultValue
from apps.results.services.result_capture import save_sheet
from apps.results.services.validation import validate_results
from apps.results.tests.test_results import ResultsTestBase

# Suman 100: el caso bueno. Las pruebas lo desvían a propósito.
FORMULA = {"HEM_NEUTROFILOS": "60", "HEM_LINFOCITOS": "32", "HEM_EOSINOFILOS": "2",
           "HEM_MONOCITOS": "5", "HEM_BASOFILOS": "1"}
RESTO = {"HEM_HEMOGLOBINA": "13,4", "HEM_HEMATOCRITO": "42",
         "HEM_GLOBULOS_BLANCOS": "7200", "HEM_PLAQUETAS": "250000"}


class SumaLeucocitariaTests(ResultsTestBase):
    def guardar(self, **cambios):
        """Guarda la hematología con la fórmula indicada y devuelve sus avisos."""
        valores = {**RESTO, **FORMULA, **cambios}
        valores = {code: raw for code, raw in valores.items() if raw is not None}
        order = self.order("HEM_COMP")
        sheet = save_sheet(order, entries=self.entries(**valores), user=self.tech)
        self.order_guardada = order
        return [w for w in sheet.warnings if "leucocitaria" in w or "falta cargar" in w]

    def test_calla_cuando_la_formula_suma_100(self):
        assert self.guardar() == []

    def test_calla_dentro_de_la_tolerancia(self):
        assert self.guardar(HEM_BASOFILOS="2") == []   # 101
        assert self.guardar(HEM_BASOFILOS="0") == []   # 99

    def test_avisa_cuando_la_suma_se_pasa_de_la_tolerancia(self):
        avisos = self.guardar(HEM_NEUTROFILOS="64")  # 104
        assert len(avisos) == 1
        assert "suma 104 %" in avisos[0]
        assert "debería sumar 100 %" in avisos[0]
        assert "HEMATOLOGÍA COMPLETA" in avisos[0]

    def test_avisa_cuando_la_suma_se_queda_corta(self):
        avisos = self.guardar(HEM_NEUTROFILOS="54")  # 94
        assert "suma 94 %" in avisos[0]

    def test_avisa_cuando_falta_cargar_alguno(self):
        avisos = self.guardar(HEM_BASOFILOS=None, HEM_MONOCITOS=None)
        assert len(avisos) == 1
        assert "falta cargar MONOCITOS y BASÓFILOS" in avisos[0]
        # Con un hueco la suma no se nombra: no hay nada que sumar todavía.
        assert "suma" not in avisos[0]

    def test_calla_si_no_se_cargo_ningun_leucocito(self):
        sin_formula = dict.fromkeys(FORMULA, None)
        assert self.guardar(**sin_formula) == []

    def test_calla_si_el_laboratorio_desactivo_uno_de_los_cinco(self):
        """Punto ciego conocido de tener la regla en código (ADR-042)."""
        Parameter.objects.filter(code="HEM_BASOFILOS").update(is_active=False)
        assert self.guardar(HEM_BASOFILOS=None, HEM_NEUTROFILOS="64") == []

    def test_el_aviso_no_bloquea_el_guardado(self):
        self.guardar(HEM_NEUTROFILOS="64")
        value = ResultValue.objects.get(parameter__code="HEM_NEUTROFILOS")
        assert value.value_numeric == 64
        assert Result.objects.get(order_item__test__code="HEM_COMP").status == (
            Result.Status.CARGADO)

    def test_el_aviso_no_bloquea_la_validacion(self):
        self.guardar(HEM_NEUTROFILOS="64")
        validate_results(order=self.order_guardada, user=self.bio)
        assert Result.objects.get(order_item__test__code="HEM_COMP").is_validated

    def test_calla_cuando_el_examen_ya_esta_validado(self):
        self.guardar(HEM_NEUTROFILOS="64")
        order = self.order_guardada
        validate_results(order=order, user=self.bio)
        sheet = save_sheet(order, entries={}, user=None)
        assert [w for w in sheet.warnings if "leucocitaria" in w] == []
