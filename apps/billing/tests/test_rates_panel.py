"""La tarjeta de tasa de cambio muestra lo mismo que se aplica a los montos.

Antes leía sólo `billing.ExchangeRate` y decía "sin registrar" aunque la tasa oficial
del BCV estuviera vigente. El riesgo no era cosmético: invitaba a cargar una tasa a
mano que, por ser de fecha igual o posterior, pisaba a la oficial y desactivaba el
automatismo diario sin aviso.
"""
import datetime
from decimal import Decimal

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.billing.context_processors import _rate_of_the_day
from apps.billing.models import Currency
from apps.billing.selectors.price_queries import latest_rates
from apps.billing.services.exchange import (
    BCV,
    LABORATORIO,
    get_exchange_rate,
    register_exchange_rate,
)
from apps.masterdata.services.bcv import register_official_rate

D = Decimal


class TarjetaDeTasaTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.usd = Currency.objects.create(code="USD", name="Dólar", symbol="$",
                                           is_base=True)
        self.ves = Currency.objects.create(code="VES", name="Bolívar", symbol="Bs.")
        self.hoy = timezone.localdate()

    def _fila(self):
        filas = [f for f in latest_rates() if f["currency"].pk == self.ves.pk]
        self.assertEqual(len(filas), 1)
        return filas[0]

    def test_sin_ninguna_tasa_la_fila_queda_vacia(self):
        self.assertIsNone(self._fila()["rate"])

    def test_muestra_la_oficial_cuando_el_laboratorio_no_carga_ninguna(self):
        register_official_rate(rate=D("887.302"), effective_date=self.hoy)
        fila = self._fila()
        self.assertEqual(fila["rate"].rate, D("887.302"))
        self.assertEqual(fila["rate"].origin, BCV)

    def test_la_del_laboratorio_se_identifica_como_tal(self):
        register_exchange_rate(from_currency=self.usd, to_currency=self.ves,
                               rate=D("900"), effective_date=self.hoy)
        fila = self._fila()
        self.assertEqual(fila["rate"].rate, D("900"))
        self.assertEqual(fila["rate"].origin, LABORATORIO)

    def test_coincide_con_la_tasa_que_se_aplica_a_los_montos(self):
        """El punto de todo el cambio: una sola fuente de verdad."""
        register_official_rate(rate=D("887.302"), effective_date=self.hoy)
        register_exchange_rate(
            from_currency=self.usd, to_currency=self.ves, rate=D("900"),
            effective_date=self.hoy - datetime.timedelta(days=2),
        )
        self.assertEqual(
            self._fila()["rate"].rate,
            get_exchange_rate(from_currency=self.usd, to_currency=self.ves,
                              on_date=self.hoy),
        )

    def test_no_muestra_una_tasa_con_fecha_futura(self):
        register_official_rate(rate=D("999"),
                               effective_date=self.hoy + datetime.timedelta(days=1))
        self.assertIsNone(self._fila()["rate"])


class BarraSuperiorTests(TenantTestCase):
    """La tasa que se muestra en la barra superior de todas las pantallas."""

    def setUp(self):
        super().setUp()
        self.usd = Currency.objects.create(code="USD", name="Dólar", symbol="$",
                                           is_base=True)
        self.ves = Currency.objects.create(code="VES", name="Bolívar", symbol="Bs.")

    def test_sin_tasa_no_muestra_nada(self):
        self.assertIsNone(_rate_of_the_day())

    def test_muestra_la_primera_moneda_con_tasa(self):
        register_official_rate(rate=D("887.302"), effective_date=timezone.localdate())
        dato = _rate_of_the_day()
        self.assertEqual(dato["base"], self.usd)
        self.assertEqual(dato["currency"], self.ves)
        self.assertEqual(dato["info"].rate, D("887.302"))
        self.assertEqual(dato["info"].origin, BCV)

    def test_ignora_las_monedas_sin_tasa(self):
        """Con dos monedas y tasa en una sola, la barra muestra ésa y no un hueco."""
        Currency.objects.create(code="EUR", name="Euro", symbol="€")
        register_official_rate(rate=D("887.302"), effective_date=timezone.localdate())
        self.assertEqual(_rate_of_the_day()["currency"], self.ves)
