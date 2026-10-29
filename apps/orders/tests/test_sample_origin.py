"""Procedencia de la muestra: las que llegan ya tomadas (Fase 09).

La depuración de creatinina es el caso que obligó a ponerlo en la muestra y no en la
orden: necesita el envase de orina de 24 h —que el paciente trae de casa por fuerza— y un
tubo de sangre que se toma en la recepción. Misma orden, dos procedencias.
"""
import datetime

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.core.exceptions import ApplicationError
from apps.orders.models import Order, Sample
from apps.orders.services.order_creation import create_order
from apps.orders.services.sample_collection import collect_sample, receive_sample
from apps.orders.tests.factories import catalogo, paciente

HACE_CINCO_HORAS = datetime.timedelta(hours=5)


class ProcedenciaTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.c = catalogo()
        self.t = self.c["tests"]
        # DEP = envase de orina de 24 h + tubo rojo: el caso real de dos procedencias.
        self.order, _ = create_order(patient=paciente(), tests=[self.t["DEP"]],
                                     price_list=self.c["lista"])
        self.envase, self.rojo = self.order.samples.order_by("sequence")
        self.ayer = timezone.now() - HACE_CINCO_HORAS

    def _recibir(self, sample=None, **kw):
        datos = {"origin": Sample.Origin.PACIENTE, "collected_at": self.ayer}
        datos.update(kw)
        return receive_sample(sample=sample or self.envase, **datos)

    # --- lo que hace -------------------------------------------------------------------
    def test_la_muestra_queda_tomada_con_su_hora_declarada(self):
        muestra = self._recibir()
        assert muestra.status == Sample.Status.TOMADA
        assert muestra.collected_at == self.ayer
        assert muestra.origin == Sample.Origin.PACIENTE
        assert muestra.arrived_collected is True

    def test_no_se_atribuye_la_toma_a_nadie_del_laboratorio(self):
        """`collected_by` vacío a propósito: nadie de aquí la tomó, y la firma de un
        informe se sostiene sobre ese dato."""
        assert self._recibir().collected_by is None

    def test_sale_de_la_lista_de_muestras_por_tomar(self):
        self._recibir()
        pendientes = self.order.samples.filter(status=Sample.Status.PENDIENTE)
        assert list(pendientes) == [self.rojo]

    def test_una_orden_puede_mezclar_las_dos_procedencias(self):
        self._recibir()
        collect_sample(sample=self.rojo)
        self.order.refresh_from_db()
        assert self.order.status == Order.Status.MUESTRA_TOMADA
        origenes = dict(self.order.samples.values_list("sequence", "origin"))
        assert origenes == {1: Sample.Origin.PACIENTE, 2: Sample.Origin.LABORATORIO}

    def test_guarda_el_detalle_de_quien_la_trajo(self):
        muestra = self._recibir(origin=Sample.Origin.REFERIDA,
                                origin_detail="  Laboratorio San José  ")
        assert muestra.origin_detail == "Laboratorio San José"

    # --- lo que no deja hacer ----------------------------------------------------------
    def test_la_procedencia_laboratorio_no_entra_por_aqui(self):
        with pytest.raises(ApplicationError, match="toma normal"):
            self._recibir(origin=Sample.Origin.LABORATORIO)

    def test_una_procedencia_inventada_se_rechaza(self):
        with pytest.raises(ApplicationError, match="no es una procedencia"):
            self._recibir(origin="DEL_ESPACIO")

    def test_exige_la_hora_de_toma(self):
        """Poner la de ahora sería inventarla: una muestra de hace cinco horas y una
        recién tomada no se leen igual."""
        with pytest.raises(ApplicationError, match="hora en que se tomó"):
            self._recibir(collected_at=None)

    def test_rechaza_una_hora_futura(self):
        futuro = timezone.now() + datetime.timedelta(hours=1)
        with pytest.raises(ApplicationError, match="futuro"):
            self._recibir(collected_at=futuro)

    def test_no_recibe_una_muestra_ya_rechazada(self):
        self.envase.status = Sample.Status.RECHAZADA
        self.envase.save(update_fields=["status"])
        with pytest.raises(ApplicationError, match="rechazada"):
            self._recibir()

    def test_no_recibe_nada_de_una_orden_anulada(self):
        self.order.status = Order.Status.ANULADA
        self.order.save(update_fields=["status"])
        with pytest.raises(ApplicationError, match="anulada"):
            self._recibir()


class DetalleSoloExternoTests(TenantTestCase):
    """La restricción vive en la base, no sólo en el servicio: el detalle de procedencia
    en una muestra tomada aquí no tiene a quién atribuirse, y suelto acabaría usándose de
    campo de notas —que ya existe en la orden."""

    def setUp(self):
        super().setUp()
        self.c = catalogo()
        self.order, _ = create_order(patient=paciente(), tests=[self.c["tests"]["HEM"]],
                                     price_list=self.c["lista"])

    def test_la_base_rechaza_un_detalle_sin_procedencia_externa(self):
        muestra = self.order.samples.first()
        muestra.origin_detail = "Clínica Razetti"
        with pytest.raises(IntegrityError):
            muestra.save(update_fields=["origin_detail"])
