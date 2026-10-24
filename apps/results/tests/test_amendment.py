"""Rectificaciones (Fase 15, ADR-035).

Lo que se prueba es lo que importa clínicamente: que lo entregado nunca se altere, que
quede registrado qué decía antes y por qué cambió, y que el informe corregido salga como
versión nueva y sellada.
"""
import pytest
from django_tenants.test.client import TenantClient

from apps.accounts.models import Membership, Role
from apps.accounts.services.user_management import seed_system_roles
from apps.core.exceptions import ApplicationError
from apps.reports.services.report_emission import emit_report, is_outdated
from apps.results.models import Result, ResultAmendment, ResultValue
from apps.results.services.amendment import amend_result
from apps.results.services.result_capture import save_sheet
from apps.results.services.validation import validate_results
from apps.results.tests.test_results import ResultsTestBase


class AmendmentTestBase(ResultsTestBase):
    def validated_order(self, raw="50"):
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL=raw), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)
        return order, Result.objects.get()


class AmendResultTests(AmendmentTestBase):
    def test_rectificar_congela_lo_anterior_y_reabre_el_examen(self):
        order, result = self.validated_order("50")

        amendment = amend_result(result=result, reason="Suero hemolizado", user=self.bio)

        result.refresh_from_db()
        assert result.status == Result.Status.CARGADO  # reabierto para corregir
        assert (result.validated_by, result.validated_at) == (None, None)
        assert amendment.version == 1 and amendment.is_open
        # El snapshot guarda lo que decía, ya formateado para leer.
        assert amendment.snapshot["values"][0]["value"] == "50,0"
        assert amendment.snapshot["validated_by"] == (self.bio.get_full_name()
                                                       or self.bio.get_username())

    def test_al_validar_de_nuevo_queda_rectificado_y_cierra_la_rectificacion(self):
        order, result = self.validated_order("50")
        amend_result(result=result, reason="Suero hemolizado", user=self.bio)

        save_sheet(order, entries=self.entries(LIP_HDL="62"), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)

        result.refresh_from_db()
        assert result.status == Result.Status.RECTIFICADO
        assert result.is_validated  # sigue siendo inmutable
        assert not ResultAmendment.objects.get().is_open
        assert ResultValue.objects.get().value_numeric == 62

    def test_el_motivo_es_obligatorio(self):
        _order, result = self.validated_order()

        with pytest.raises(ApplicationError, match="motivo"):
            amend_result(result=result, reason="   ", user=self.bio)

        assert not ResultAmendment.objects.exists()
        result.refresh_from_db()
        assert result.is_validated  # no se reabrió

    def test_no_se_rectifica_lo_que_no_esta_validado(self):
        order = self.order("HDL")
        save_sheet(order, entries=self.entries(LIP_HDL="50"), user=self.tech)

        with pytest.raises(ApplicationError, match="no está validado"):
            amend_result(result=Result.objects.get(), reason="x", user=self.bio)

    def test_no_se_abren_dos_rectificaciones_a_la_vez(self):
        _order, result = self.validated_order()
        amend_result(result=result, reason="Primera", user=self.bio)

        with pytest.raises(ApplicationError, match="ya tiene una rectificación abierta"):
            amend_result(result=result, reason="Segunda", user=self.bio)

    def test_se_pueden_encadenar_rectificaciones(self):
        order, result = self.validated_order("50")
        amend_result(result=result, reason="Primera", user=self.bio)
        save_sheet(order, entries=self.entries(LIP_HDL="62"), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)

        result.refresh_from_db()
        second = amend_result(result=result, reason="Segunda", user=self.bio)

        assert second.version == 2
        assert ResultAmendment.objects.count() == 2
        assert second.snapshot["values"][0]["value"] == "62,0"  # congela lo corregido


class AmendedReportTests(AmendmentTestBase):
    def test_el_informe_corregido_es_una_version_nueva_y_la_anterior_queda_intacta(self):
        order, result = self.validated_order("50")
        first, _ = emit_report(order=order, user=self.bio)

        amend_result(result=result, reason="Suero hemolizado", user=self.bio)
        save_sheet(order, entries=self.entries(LIP_HDL="62"), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)
        second, created = emit_report(order=order, user=self.bio)

        assert created and second.version == 2
        assert second.previous_hash == first.content_hash  # encadenados
        first.refresh_from_db()
        assert not first.is_current
        # Lo que el paciente recibió sigue diciendo lo mismo, para siempre.
        assert first.payload["sections"][0]["tests"][0]["rows"][0]["value"] == "50,0"
        assert second.payload["sections"][0]["tests"][0]["rows"][0]["value"] == "62,0"

    def test_el_informe_nuevo_viene_sellado_como_rectificado(self):
        order, result = self.validated_order("50")
        emit_report(order=order, user=self.bio)
        amend_result(result=result, reason="Suero hemolizado", user=self.bio)
        save_sheet(order, entries=self.entries(LIP_HDL="62"), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)

        report, _ = emit_report(order=order, user=self.bio)

        assert report.payload["amended_tests"] == [result.order_item.test.name]
        assert report.payload["sections"][0]["tests"][0]["amended"] is True
        # El motivo es interno: nunca viaja al contenido del informe.
        assert "hemolizado" not in str(report.payload)

    def test_una_orden_sin_rectificaciones_conserva_su_huella(self):
        """La Fase 15 no debe marcar como desactualizados los informes ya emitidos."""
        order, _result = self.validated_order("50")
        report, _ = emit_report(order=order, user=self.bio)

        assert "amended_tests" not in report.payload
        assert "amended" not in report.payload["sections"][0]["tests"][0]
        assert not is_outdated(report, order)

    def test_un_examen_rectificado_sigue_entrando_al_informe(self):
        """Si el filtro del selector no contemplara RECTIFICADO, el examen corregido
        desaparecería del informe — justo lo contrario de lo que se busca."""
        order, result = self.validated_order("50")
        amend_result(result=result, reason="Suero hemolizado", user=self.bio)
        save_sheet(order, entries=self.entries(LIP_HDL="62"), user=self.tech)
        validate_results(order=order, result_ids=[], user=self.bio)

        report, _ = emit_report(order=order, user=self.bio)

        assert report.payload["test_count"] == 1
        assert report.payload["kind"] == "FINAL"


class AmendViewTests(AmendmentTestBase):
    def setUp(self):
        super().setUp()
        seed_system_roles()
        Membership.objects.create(user=self.tech, role=Role.objects.get(code="TECNICO"))
        Membership.objects.create(user=self.bio,
                                   role=Role.objects.get(code="BIOANALISTA"))
        self.client = TenantClient(self.tenant)

    def test_el_tecnico_no_puede_rectificar(self):
        order, result = self.validated_order()
        self.client.force_login(self.tech)

        response = self.client.post(
            f"/resultados/orden/{order.pk}/examenes/{result.pk}/rectificar/",
            {"reason": "Suero hemolizado"})

        assert response.status_code == 403
        assert not ResultAmendment.objects.exists()
        result.refresh_from_db()
        assert result.is_validated

    def test_el_bioanalista_rectifica_desde_la_pantalla(self):
        order, result = self.validated_order()
        self.client.force_login(self.bio)

        response = self.client.post(
            f"/resultados/orden/{order.pk}/examenes/{result.pk}/rectificar/",
            {"reason": "Suero hemolizado"})

        assert response.status_code == 302
        assert ResultAmendment.objects.get().reason == "Suero hemolizado"
        html = self.client.get(f"/resultados/orden/{order.pk}/").content.decode()
        assert "Rectificaciones" in html and "Suero hemolizado" in html

    def test_la_pantalla_ofrece_rectificar_solo_sobre_lo_validado(self):
        order, _result = self.validated_order()
        self.client.force_login(self.bio)

        html = self.client.get(f"/resultados/orden/{order.pk}/").content.decode()

        assert "Rectificar" in html
        assert "no se imprime en el informe" in html
