"""Bloques de numeración (Fase 14): lo que garantiza que una orden creada sin conexión
nazca con su número definitivo y que ese número no se le dé a nadie más."""
import datetime

import pytest
from django_tenants.test.cases import TenantTestCase

from apps.core.exceptions import ApplicationError
from apps.orders.models import Order
from apps.orders.services.numbering import next_order_number
from apps.orders.services.order_creation import create_order
from apps.orders.tests.factories import catalogo, paciente
from apps.sync.models import Device
from apps.sync.services.number_blocks import (
    number_from_block,
    parse_order_number,
    reserve_block,
)


class NumberBlockTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.device = Device.objects.create(device_id="tablet-1", label="Tablet toma")
        self.today = datetime.date.today()

    def test_el_bloque_sale_de_la_secuencia_y_la_recepcion_no_pisa_sus_numeros(self):
        block = reserve_block(device=self.device, size=5)

        assert (block.from_value, block.to_value) == (1, 5)
        # El siguiente número en línea arranca después del bloque: nunca se repite.
        assert next_order_number(on_date=self.today).endswith("-0006")

    def test_dos_bloques_del_mismo_dia_no_se_solapan(self):
        first = reserve_block(device=self.device, size=3)
        second = reserve_block(device=self.device, size=3)

        assert (first.from_value, first.to_value) == (1, 3)
        assert (second.from_value, second.to_value) == (4, 6)

    def test_otro_dispositivo_no_puede_usar_un_numero_ajeno(self):
        block = reserve_block(device=self.device, size=2)
        intruder = Device.objects.create(device_id="tablet-2")
        number = f"{block.day:%y%m%d}-{block.from_value:04d}"

        assert number_from_block(device=self.device, number=number) == block
        with pytest.raises(ApplicationError, match="no corresponde a un bloque"):
            number_from_block(device=intruder, number=number)

    def test_un_numero_ya_usado_se_rechaza(self):
        data = catalogo()
        block = reserve_block(device=self.device, size=2)
        number = f"{block.day:%y%m%d}-{block.from_value:04d}"
        create_order(patient=paciente(), tests=[data["tests"]["HEM"]], number=number)

        assert Order.objects.filter(number=number).exists()
        with pytest.raises(ApplicationError, match="Ya existe una orden"):
            number_from_block(device=self.device, number=number)

    def test_numero_mal_formado_o_fuera_de_rango(self):
        assert parse_order_number("261014-0007") == (datetime.date(2026, 10, 14), 7)
        for bad in ("261014", "AAAAAA-0001", "261014-0000"):
            with pytest.raises(ApplicationError):
                parse_order_number(bad)
