"""Precedencia entre la tasa del laboratorio y la tasa oficial global (ADR-035)."""
import datetime
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase

from apps.billing.models import Currency
from apps.billing.services.exchange import get_exchange_rate, register_exchange_rate
from apps.core.exceptions import ApplicationError
from apps.masterdata.services.bcv import register_official_rate

D = Decimal
HOY = datetime.date(2026, 10, 20)
AYER = HOY - datetime.timedelta(days=1)


class TasaOficialTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.usd = Currency.objects.create(code="USD", name="Dólar", symbol="$",
                                           is_base=True)
        self.ves = Currency.objects.create(code="VES", name="Bolívar", symbol="Bs.")

    def _tasa(self, on_date=HOY):
        return get_exchange_rate(from_currency=self.usd, to_currency=self.ves,
                                 on_date=on_date)

    def test_sin_ninguna_tasa_no_inventa_una(self):
        with self.assertRaises(ApplicationError):
            self._tasa()

    def test_usa_la_oficial_cuando_el_laboratorio_no_carga_ninguna(self):
        register_official_rate(rate=D("300"), effective_date=HOY)
        self.assertEqual(self._tasa(), D("300"))

    def test_la_del_laboratorio_manda_en_el_mismo_dia(self):
        """Si el laboratorio la cargó a mano teniendo la oficial, fue por algo."""
        register_official_rate(rate=D("300"), effective_date=HOY)
        register_exchange_rate(from_currency=self.usd, to_currency=self.ves,
                               rate=D("310"), effective_date=HOY)
        self.assertEqual(self._tasa(), D("310"))

    def test_una_oficial_mas_reciente_reemplaza_a_la_del_laboratorio(self):
        register_exchange_rate(from_currency=self.usd, to_currency=self.ves,
                               rate=D("310"), effective_date=AYER)
        register_official_rate(rate=D("320"), effective_date=HOY)
        self.assertEqual(self._tasa(), D("320"))

    def test_no_usa_una_tasa_del_futuro(self):
        register_official_rate(rate=D("300"), effective_date=AYER)
        register_official_rate(rate=D("999"), effective_date=HOY)
        self.assertEqual(self._tasa(on_date=AYER), D("300"))

    def test_la_oficial_inversa_se_invierte(self):
        register_official_rate(rate=D("0.004"), from_code="VES", to_code="USD",
                               effective_date=HOY)
        self.assertEqual(self._tasa(), D(1) / D("0.004"))

    def test_misma_moneda_sigue_siendo_uno(self):
        self.assertEqual(
            get_exchange_rate(from_currency=self.usd, to_currency=self.usd, on_date=HOY),
            D(1),
        )
