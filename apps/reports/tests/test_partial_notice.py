"""El aviso de informe parcial es opcional (ADR-043).

Apagado, se van la insignia PARCIAL de la cabecera y el recuadro que lista lo pendiente.
La versión sigue siendo PARCIAL: eso es un hecho de la orden, no una preferencia.
"""
from apps.reports.services.report_emission import emit_report
from apps.reports.services.report_payload import build_payload, content_hash
from apps.reports.services.report_pdf import _anuncia_parcial, render_report_pdf
from apps.reports.tests.test_reports import ReportTestBase
from apps.settings_lab.models import TenantSettings


class AvisoDeParcialOpcionalTests(ReportTestBase):
    def parcial(self):
        """Orden con un examen validado y otro pendiente por validar."""
        return self.validated_lipids(extra=("TRIGLICERIDOS",))

    @staticmethod
    def apagar():
        settings_obj = TenantSettings.get_solo()
        settings_obj.report_partial_notice = False
        settings_obj.save(update_fields=["report_partial_notice"])

    def test_encendido_por_defecto_y_sin_clave_en_el_contenido(self):
        payload = build_payload(self.parcial())
        # Ausente = encendido. Si se agregara siempre, cambiaría la huella de todos los
        # informes ya emitidos y quedarían marcados como desactualizados.
        assert "partial_notice" not in payload
        assert _anuncia_parcial(payload) is True

    def test_apagado_agrega_la_clave_y_calla_el_aviso(self):
        self.apagar()
        payload = build_payload(self.parcial())
        assert payload["partial_notice"] is False
        assert _anuncia_parcial(payload) is False

    def test_apagarlo_no_cambia_el_tipo_ni_lo_pendiente(self):
        """El informe se sigue identificando como parcial en la línea de la versión."""
        self.apagar()
        payload = build_payload(self.parcial())
        assert payload["kind"] == "PARCIAL"
        assert payload["pending_tests"]

    def test_apagarlo_cambia_la_huella_del_parcial(self):
        order = self.parcial()
        antes = content_hash(build_payload(order))
        self.apagar()
        assert content_hash(build_payload(order)) != antes

    def test_un_informe_final_no_se_entera(self):
        """Apagar un aviso que no le toca no debe dejar obsoletos los finales."""
        order = self.validated_lipids()
        antes = content_hash(build_payload(order))
        self.apagar()
        despues = build_payload(order)
        assert despues["kind"] == "FINAL"
        assert "partial_notice" not in despues
        assert content_hash(despues) == antes

    def test_el_pdf_de_un_parcial_sin_aviso_se_genera(self):
        self.apagar()
        report, _ = emit_report(order=self.parcial(), user=self.bio)
        assert report.is_partial
        pdf = render_report_pdf(report, verify_url="https://lab.test/verificar/x/")
        assert pdf.startswith(b"%PDF")
