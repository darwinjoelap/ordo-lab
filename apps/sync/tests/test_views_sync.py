"""Endpoints de sincronización (Fase 14): sesión obligatoria, JSON y reenvío inocuo."""
import json
import uuid

from django_tenants.test.client import TenantClient

from apps.orders.models import Sample
from apps.sync.models import Device, SyncQueueEntry
from apps.sync.tests.test_apply import SyncTestBase, mutation

MUTATIONS_URL = "/sincronizacion/mutaciones/"
BLOCK_URL = "/sincronizacion/bloque/"


class SyncEndpointTests(SyncTestBase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def post(self, url, data):
        return self.client.post(url, data=json.dumps(data),
                                content_type="application/json")

    def test_sin_sesion_no_se_sincroniza(self):
        response = self.post(MUTATIONS_URL, {"device_id": "x", "mutations": []})

        assert response.status_code == 302  # al login
        assert not SyncQueueEntry.objects.exists()

    def test_reserva_de_bloque_devuelve_los_numeros_del_dia(self):
        self.client.force_login(self.bio)

        data = self.post(BLOCK_URL, {"device_id": "tablet-9", "size": 3}).json()

        assert data["from"] == 1 and data["to"] == 3
        assert len(data["numbers"]) == 3 and data["numbers"][0].endswith("-0001")
        assert Device.objects.filter(device_id="tablet-9").exists()

    def test_el_lote_se_aplica_y_reenviarlo_no_duplica(self):
        self.client.force_login(self.tech)
        order = self.pending_order("HDL")
        sample = order.samples.first()
        body = {"device_id": self.device.device_id, "mutations": [mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})]}

        first = self.post(MUTATIONS_URL, body).json()
        second = self.post(MUTATIONS_URL, body).json()

        assert first["results"][0]["status"] == SyncQueueEntry.Status.APLICADO
        assert second["results"][0]["status"] == SyncQueueEntry.Status.APLICADO
        assert SyncQueueEntry.objects.count() == 1
        sample.refresh_from_db()
        assert sample.status == Sample.Status.TOMADA

    def test_cuerpo_invalido_o_lote_gigante_responden_400(self):
        self.client.force_login(self.tech)

        assert self.client.post(MUTATIONS_URL, data="{no json",
                                content_type="application/json").status_code == 400
        assert self.post(MUTATIONS_URL, {"mutations": []}).status_code == 400  # sin device
        gigante = {"device_id": "d", "mutations": [
            mutation(SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(uuid.uuid4())})
            for _ in range(201)]}
        assert self.post(MUTATIONS_URL, gigante).status_code == 400

    def test_estado_cuenta_pendientes_y_conflictos(self):
        self.client.force_login(self.tech)
        self.post(MUTATIONS_URL, {"device_id": "d", "mutations": [mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(uuid.uuid4())})]})

        data = self.client.get("/sincronizacion/estado/").json()

        assert data["errores"] == 1 and data["conflictos"] == 0
