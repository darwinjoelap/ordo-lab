"""Aplicación de mutaciones offline (Fase 14).

Lo que se prueba aquí es lo que cuesta caro si falla: que reenviar no duplique, que el
servidor sea quien calcula y marca, y que un resultado validado no se altere nunca.
"""
import datetime
import uuid

from django.utils import timezone

from apps.accounts.models import Membership, Role
from apps.accounts.services.user_management import seed_system_roles
from apps.catalog.models import Test
from apps.orders.models import Order, Sample
from apps.orders.services.order_creation import create_order
from apps.patients.models import Patient
from apps.results.models import Result, ResultValue
from apps.results.services.result_capture import save_sheet
from apps.results.services.validation import validate_results
from apps.results.tests.test_results import ResultsTestBase
from apps.sync.models import Device, SyncConflict, SyncQueueEntry
from apps.sync.services.apply import receive
from apps.sync.services.number_blocks import reserve_block


def mutation(kind: str, payload: dict, *, when=None, mutation_id=None) -> dict:
    return {
        "client_mutation_id": str(mutation_id or uuid.uuid4()),
        "kind": kind,
        "client_created_at": (when or timezone.now()).isoformat(),
        "payload": payload,
    }


class SyncTestBase(ResultsTestBase):
    def setUp(self):
        super().setUp()
        seed_system_roles()
        Membership.objects.create(user=self.tech, role=Role.objects.get(code="TECNICO"))
        Membership.objects.create(user=self.bio, role=Role.objects.get(code="ADMIN_LAB"))
        self.device = Device.objects.create(device_id="tablet-1", label="Tablet")

    def pending_order(self, *codes) -> Order:
        """Orden con sus tubos todavía por tomar (`self.order` los marca tomados)."""
        order, _ = create_order(patient=self.patient,
                                tests=list(Test.objects.filter(code__in=codes)))
        return order


class IdempotencyTests(SyncTestBase):
    def test_reenviar_la_misma_mutacion_no_repite_el_efecto(self):
        order = self.pending_order("HDL")
        sample = order.samples.first()
        raw = mutation(SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})

        first = receive(device=self.device, mutations=[raw], user=self.tech)
        second = receive(device=self.device, mutations=[raw, raw], user=self.tech)

        assert SyncQueueEntry.objects.count() == 1
        assert first[0].entry.status == SyncQueueEntry.Status.APLICADO
        assert all(o.entry.status == SyncQueueEntry.Status.APLICADO for o in second)
        sample.refresh_from_db()
        assert sample.status == Sample.Status.TOMADA

    def test_una_mutacion_que_falla_no_tumba_el_resto_del_lote(self):
        order = self.pending_order("HDL")
        sample = order.samples.first()
        good = mutation(SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})
        bad = mutation(SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(uuid.uuid4())})
        sin_id = {"kind": SyncQueueEntry.Kind.MUESTRA_TOMADA, "payload": {}}
        id_invalido = {"client_mutation_id": "no-es-un-uuid",
                       "kind": SyncQueueEntry.Kind.MUESTRA_TOMADA, "payload": {}}

        outcomes = receive(device=self.device, mutations=[bad, good, sin_id, id_invalido],
                           user=self.tech)

        assert [o.entry.status for o in outcomes] == [
            SyncQueueEntry.Status.ERROR, SyncQueueEntry.Status.APLICADO,
            SyncQueueEntry.Status.ERROR, SyncQueueEntry.Status.ERROR,
        ]
        assert "UUID válido" in outcomes[3].entry.error_detail
        sample.refresh_from_db()
        assert sample.status == Sample.Status.TOMADA


class SampleMutationTests(SyncTestBase):
    def test_la_toma_queda_con_la_hora_del_dispositivo_no_la_de_la_sincronizacion(self):
        order = self.pending_order("HDL")
        sample = order.samples.first()
        when = timezone.now() - datetime.timedelta(hours=5)

        receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)}, when=when)])

        sample.refresh_from_db()
        assert abs((sample.collected_at - when).total_seconds()) < 2
        assert sample.collected_by == self.tech

    def test_tubo_rechazado_en_el_laboratorio_mientras_el_dispositivo_estaba_offline(self):
        from apps.orders.services.sample_collection import reject_sample
        order = self.pending_order("HDL")
        sample = order.samples.first()
        reject_sample(sample=sample, reason="Hemólisis", user=self.bio)

        outcome = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.CONFLICTO
        assert outcome.conflicts[0].reason == SyncConflict.Reason.MUESTRA_RECHAZADA
        sample.refresh_from_db()
        assert sample.status == Sample.Status.RECHAZADA  # no se "destomó" ni se tomó


class ResultCaptureTests(SyncTestBase):
    def test_el_servidor_calcula_y_marca_lo_que_el_dispositivo_mando_en_crudo(self):
        order = self.order("HEM_COMP")

        receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk),
             "entries": self.entries(HEM_HEMOGLOBINA="6,5")})])

        value = ResultValue.objects.get(parameter__code="HEM_HEMOGLOBINA")
        # El dispositivo sólo escribió "6,5": la marca crítica y el rango los puso el
        # servidor al sincronizar.
        assert value.flag == ResultValue.Flag.CRITICO_BAJO
        assert value.reference_text == "12,0 - 16,0 g/dL"
        assert value.source == ResultValue.Source.OFFLINE_SYNC

    def test_un_resultado_validado_nunca_se_sobrescribe(self):
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL="50"), user=self.bio)
        validate_results(order=order, result_ids=[], user=self.bio)

        outcome = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk), "entries": self.entries(LIP_HDL="80")})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.CONFLICTO
        conflict = outcome.conflicts[0]
        assert conflict.reason == SyncConflict.Reason.RESULTADO_VALIDADO
        assert (conflict.client_value, conflict.server_value) == ("80", "validado")
        value = ResultValue.objects.get(parameter__code="LIP_HDL")
        assert value.value_numeric == 50  # intacto
        assert Result.objects.get().status == Result.Status.VALIDADO

    def test_si_otro_usuario_lo_cambio_primero_queda_conflicto_por_version(self):
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL="50"), user=self.bio)
        result = Result.objects.get()
        stale_version = result.sync_version - 1

        outcome = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk), "entries": self.entries(LIP_HDL="80"),
             "sync_versions": {str(result.pk): stale_version}})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.CONFLICTO
        assert outcome.conflicts[0].reason == SyncConflict.Reason.VERSION_VIEJA
        assert ResultValue.objects.get().value_numeric == 50

    def test_sin_conflicto_de_version_si_el_dispositivo_estaba_al_dia(self):
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL="50"), user=self.bio)
        result = Result.objects.get()

        outcome = receive(device=self.device, user=self.tech, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk), "entries": self.entries(LIP_HDL="80"),
             "sync_versions": {str(result.pk): result.sync_version}})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO
        assert ResultValue.objects.get().value_numeric == 80


class OrderMutationTests(SyncTestBase):
    def test_orden_offline_con_el_numero_de_su_bloque_y_la_hora_real(self):
        block = reserve_block(device=self.device, size=5)
        number = f"{block.day:%y%m%d}-{block.from_value:04d}"
        when = timezone.now() - datetime.timedelta(hours=3)
        test = Test.objects.get(code="HDL")

        outcome = receive(device=self.device, user=self.bio, mutations=[mutation(
            SyncQueueEntry.Kind.ORDEN_NUEVA,
            {"number": number, "patient_id": str(self.patient.pk),
             "test_ids": [str(test.pk)]}, when=when)])[0]

        order = Order.objects.get(number=number)
        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO
        assert str(order.client_mutation_id) == str(outcome.entry.client_mutation_id)
        assert abs((order.ordered_at - when).total_seconds()) < 2
        assert order.items.count() == 1
        assert order.samples.exists()  # los tubos se planifican al sincronizar

    def test_un_numero_que_no_es_de_su_bloque_se_rechaza(self):
        test = Test.objects.get(code="HDL")

        outcome = receive(device=self.device, user=self.bio, mutations=[mutation(
            SyncQueueEntry.Kind.ORDEN_NUEVA,
            {"number": "261014-9999", "patient_id": str(self.patient.pk),
             "test_ids": [str(test.pk)]})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.ERROR
        assert "no corresponde a un bloque" in outcome.entry.error_detail
        assert not Order.objects.filter(number="261014-9999").exists()


class PatientMutationTests(SyncTestBase):
    def test_documento_repetido_reutiliza_el_paciente_y_no_duplica(self):
        payload = {"first_name": "María", "last_name": "Pérez", "sex": "F",
                   "document_type": Patient.DocumentType.V,
                   "document_number": self.patient.document_number,
                   "birth_date": "1990-05-04"}

        outcome = receive(device=self.device, user=self.bio, mutations=[mutation(
            SyncQueueEntry.Kind.PACIENTE_NUEVO, payload)])[0]

        assert Patient.objects.count() == 1
        assert outcome.entry.target_id == self.patient.pk
        conflict = outcome.conflicts[0]
        assert conflict.reason == SyncConflict.Reason.PACIENTE_DUPLICADO
        # Ya resuelto: no manda a nadie a revisar, sólo deja la traza de la fusión.
        assert conflict.resolution == SyncConflict.Resolution.SERVIDOR
        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO

    def test_paciente_nuevo_se_crea_con_su_id_de_mutacion(self):
        payload = {"first_name": "Luis", "last_name": "Sutil", "sex": "M",
                   "document_type": Patient.DocumentType.V, "document_number": "9876543",
                   "birth_date": "1985-02-01"}
        raw = mutation(SyncQueueEntry.Kind.PACIENTE_NUEVO, payload)

        receive(device=self.device, mutations=[raw], user=self.bio)
        receive(device=self.device, mutations=[raw], user=self.bio)  # reintento

        created = Patient.objects.get(document_number="9876543")
        assert str(created.client_mutation_id) == raw["client_mutation_id"]
        assert Patient.objects.count() == 2  # el del fixture y este, sin duplicar


class PermissionTests(SyncTestBase):
    def test_el_auxiliar_de_toma_no_puede_capturar_resultados_por_la_cola(self):
        from apps.accounts.models import User
        auxiliar = User.objects.create_user(username="aux", email="a@lab.test", password="x")
        Membership.objects.create(user=auxiliar,
                                   role=Role.objects.get(code="AUXILIAR_TOMA"))
        order = self.order("HDL")

        outcome = receive(device=self.device, user=auxiliar, mutations=[mutation(
            SyncQueueEntry.Kind.RESULTADO_CAPTURADO,
            {"order_id": str(order.pk), "entries": self.entries(LIP_HDL="50")})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.ERROR
        assert "Su rol no puede" in outcome.entry.error_detail
        assert not ResultValue.objects.exists()

    def test_el_auxiliar_de_toma_si_puede_marcar_tubos(self):
        from apps.accounts.models import User
        auxiliar = User.objects.create_user(username="aux2", email="a2@lab.test",
                                             password="x")
        Membership.objects.create(user=auxiliar,
                                   role=Role.objects.get(code="AUXILIAR_TOMA"))
        order = self.pending_order("HDL")
        sample = order.samples.first()

        outcome = receive(device=self.device, user=auxiliar, mutations=[mutation(
            SyncQueueEntry.Kind.MUESTRA_TOMADA, {"sample_id": str(sample.pk)})])[0]

        assert outcome.entry.status == SyncQueueEntry.Status.APLICADO
