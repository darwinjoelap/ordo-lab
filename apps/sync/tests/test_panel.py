"""Pantalla de Sincronización y reintentos (Fase 14, tramo C), y el contrato entre las
plantillas y `static/js/sync.js` (tramo B).

El JavaScript no se prueba aquí — el proyecto no tiene infraestructura de tests de JS —
pero sí se prueba que las plantillas publiquen los atributos `data-offline` que el
cliente necesita: si alguien los quita al editar una pantalla, la captura offline dejaría
de funcionar en silencio y esto lo detecta.
"""
import json
import re
import uuid

from django_tenants.test.client import TenantClient

from apps.accounts.models import Membership, Role
from apps.catalog.models import Test
from apps.results.models import Result
from apps.results.services.result_capture import save_sheet
from apps.results.services.validation import validate_results
from apps.sync.models import SyncConflict, SyncQueueEntry
from apps.sync.services.apply import receive, retry_entry
from apps.sync.tests.test_apply import SyncTestBase, mutation


class RetryTests(SyncTestBase):
    def test_reintentar_aplica_lo_que_habia_fallado(self):
        order = self.pending_order("HDL")
        sample = order.samples.first()
        # Falla porque el id no existe todavía (caso típico: llegó en desorden).
        entry = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA,
            {"sample_id": str(uuid.uuid4())})])[0].entry
        assert entry.status == SyncQueueEntry.Status.ERROR

        entry.payload = {"sample_id": str(sample.pk)}
        entry.save(update_fields=["payload"])
        outcome = retry_entry(entry, user=self.tech)

        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO
        sample.refresh_from_db()
        assert sample.status == "TOMADA"

    def test_una_mutacion_ya_aplicada_no_se_reintenta(self):
        order = self.pending_order("HDL")
        sample = order.samples.first()
        entry = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})])[0].entry
        applied_at = entry.applied_at

        outcome = retry_entry(entry, user=self.tech)

        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO
        entry.refresh_from_db()
        assert entry.applied_at == applied_at  # no se volvió a aplicar


class PanelTests(SyncTestBase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def conflict(self) -> SyncConflict:
        """Crea un conflicto real: captura offline de un resultado ya validado."""
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL="50"), user=self.bio)
        validate_results(order=order, result_ids=[], user=self.bio)
        receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk), "entries": self.entries(LIP_HDL="80")})])
        return SyncConflict.objects.get()

    def test_la_pantalla_muestra_el_conflicto_y_su_valor_rechazado(self):
        self.conflict()
        self.client.force_login(self.bio)

        html = self.client.get("/sincronizacion/").content.decode()

        assert "Por revisar" in html
        assert "ya estaba validado" in html
        assert "Revisado" in html  # el bioanalista sí puede resolver

    def test_el_tecnico_ve_la_pantalla_pero_no_resuelve(self):
        conflict = self.conflict()
        self.client.force_login(self.tech)

        html = self.client.get("/sincronizacion/").content.decode()
        assert "lo revisa el bioanalista" in html

        response = self.client.post(f"/sincronizacion/conflictos/{conflict.pk}/revisado/",
                                     {"notes": "yo lo vi"})
        assert response.status_code == 403
        conflict.refresh_from_db()
        assert conflict.resolution == SyncConflict.Resolution.PENDIENTE

    def test_marcar_revisado_no_toca_el_resultado_validado(self):
        conflict = self.conflict()
        self.client.force_login(self.bio)

        self.client.post(f"/sincronizacion/conflictos/{conflict.pk}/revisado/",
                         {"notes": "Se repite el examen"})

        conflict.refresh_from_db()
        assert conflict.resolution == SyncConflict.Resolution.SERVIDOR
        assert (conflict.resolved_by, conflict.notes) == (self.bio, "Se repite el examen")
        assert conflict.resolved_at is not None
        # Lo que motivó el conflicto sigue intacto.
        assert Result.objects.get().status == Result.Status.VALIDADO

    def test_reintentar_desde_la_pantalla(self):
        entry = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA,
            {"sample_id": str(uuid.uuid4())})])[0].entry
        self.client.force_login(self.tech)

        response = self.client.post(f"/sincronizacion/{entry.pk}/reintentar/")

        assert response.status_code == 302
        entry.refresh_from_db()
        assert entry.status == SyncQueueEntry.Status.ERROR  # sigue fallando, pero avisa


class OfflineTemplateContractTests(SyncTestBase):
    """Los atributos que `static/js/sync.js` necesita para armar cada mutación."""

    def setUp(self):
        super().setUp()
        Membership.objects.create(user=self.tech,
                                   role=Role.objects.get(code="AUXILIAR_TOMA"))
        self.client = TenantClient(self.tenant)
        self.client.force_login(self.tech)

    def test_la_orden_publica_los_formularios_de_tubos(self):
        order = self.pending_order("HDL")

        html = self.client.get(f"/ordenes/{order.pk}/").content.decode()

        assert 'data-offline="MUESTRA_TOMADA"' in html
        assert 'data-offline-samples="' in html
        assert str(order.samples.first().pk) in html

    def test_la_captura_publica_la_orden_y_las_versiones_como_json_valido(self):
        order = self.order("HDL")
        self.client.get(f"/resultados/orden/{order.pk}/")  # crea los Result
        result = Result.objects.get()

        html = self.client.get(f"/resultados/orden/{order.pk}/").content.decode()

        assert 'data-offline="RESULTADO_CAPTURADO"' in html
        assert f'data-offline-order="{order.pk}"' in html
        raw = re.search(r"data-offline-versions='([^']+)'", html).group(1)
        assert json.loads(raw) == {str(result.pk): result.sync_version}

    def test_validar_y_cobrar_quedan_marcados_como_que_necesitan_conexion(self):
        order = self.order("HDL")

        detail = self.client.get(f"/ordenes/{order.pk}/").content.decode()
        capture = self.client.get(f"/resultados/orden/{order.pk}/").content.decode()

        assert "data-online-only" in detail
        assert "data-online-only" in capture

    def test_el_menu_y_el_aviso_traen_los_contadores(self):
        html = self.client.get(f"/ordenes/{self.pending_order('HDL').pk}/").content.decode()

        assert "data-sync-count" in html      # pendientes en este dispositivo
        assert "data-sync-review" in html     # conflictos/errores en el servidor
        assert 'id="bl-sync"' in html         # configuración que lee sync.js
        assert "dexie" in html and "js/sync" in html

    def test_las_pantallas_de_catalogo_no_declaran_nada_offline(self):
        """El alcance offline es tubos y resultados: nada más debe interceptarse."""
        tests = Test.objects.filter(code="HDL")
        assert tests.exists()
        html = self.client.get("/pacientes/").content.decode()

        assert "data-offline=" not in html
