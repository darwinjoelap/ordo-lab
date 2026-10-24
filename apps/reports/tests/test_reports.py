import datetime
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django_tenants.test.client import TenantClient
from PIL import Image as PILImage

from apps.accounts.models import Membership, Role
from apps.accounts.services.user_management import seed_system_roles
from apps.orders.models import Order
from apps.reports.models import Report
from apps.reports.services.report_emission import emit_report, is_outdated
from apps.reports.services.report_payload import build_payload
from apps.reports.services.report_pdf import render_report_pdf
from apps.results.models import Result
from apps.results.services.result_capture import build_sheet, save_sheet
from apps.results.services.validation import validate_results
from apps.results.tests.test_results import ResultsTestBase
from apps.settings_lab.models import TenantSettings

MEDIA = tempfile.mkdtemp(prefix="ordolab-media-")


def png(color="navy") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    PILImage.new("RGB", (240, 90), color).save(buffer, "PNG")
    return SimpleUploadedFile("firma.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class ReportTestBase(ResultsTestBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.bio.first_name, self.bio.last_name = "Ana", "Pérez"
        self.bio.professional_title = "Lcda. en Bioanálisis"
        self.bio.professional_license = "MPPS 12345"
        self.bio.save()

    def validated_lipids(self, *, extra=()):
        order = self.order("COLESTEROL_TOTAL", "HDL", *extra)
        build_sheet(order)
        hdl = Result.objects.get(order_item__test__code="HDL")
        save_sheet(order, entries=self.entries(LIP_COLESTEROL_TOTAL="210", LIP_HDL="50"),
                   notes={str(hdl.pk): {"observations": "SUERO LIPÉMICO"}}, user=self.tech)
        ids = [r.pk for r in Result.objects.filter(
            order_item__order=order, order_item__test__code__in=["COLESTEROL_TOTAL", "HDL"])]
        validate_results(order=order, result_ids=ids, user=self.bio)
        return order


class PayloadTests(ReportTestBase):
    def test_contenido_congelado_con_observacion_bajo_su_examen(self):
        order = self.validated_lipids()
        payload = build_payload(order)
        tests = {t["code"]: t for s in payload["sections"] for t in s["tests"]}
        assert payload["kind"] == "FINAL" and payload["test_count"] == 2
        assert tests["HDL"]["observations"] == "SUERO LIPÉMICO"
        assert tests["COLESTEROL_TOTAL"]["observations"] == ""
        row = tests["COLESTEROL_TOTAL"]["rows"][0]
        assert (row["value"], row["flag"]) == ("210", "ALTO") and row["reference"]
        assert payload["signers"][0]["name"] == "Ana Pérez"
        assert payload["signers"][0]["license"] == "MPPS 12345"
        assert payload["lab"]["footer"] == ""  # sin texto legal por defecto

    def test_parcial_lista_lo_pendiente_y_no_incluye_lo_no_validado(self):
        order = self.validated_lipids(extra=("TRIGLICERIDOS",))
        payload = build_payload(order)
        assert payload["kind"] == "PARCIAL"
        assert payload["pending_tests"] == ["TRIGLICERIDOS"] or \
            "TRIGLICÉRIDOS" in payload["pending_tests"][0].upper()
        codes = [t["code"] for s in payload["sections"] for t in s["tests"]]
        assert "TRIGLICERIDOS" not in codes


class EmissionTests(ReportTestBase):
    def test_sin_validados_no_hay_informe(self):
        from apps.core.exceptions import ApplicationError
        order = self.order("HDL")
        try:
            emit_report(order=order, user=self.bio)
        except ApplicationError as exc:
            assert "validados" in exc.message
        else:  # pragma: no cover
            raise AssertionError("debió fallar")

    def test_versiones_encadenadas_y_sin_duplicar(self):
        order = self.validated_lipids(extra=("TRIGLICERIDOS",))
        first, created = emit_report(order=order, user=self.tech)
        assert created and first.kind == "PARCIAL" and first.version == 1
        again, created = emit_report(order=order, user=self.tech)
        assert not created and again.pk == first.pk
        assert not is_outdated(first, order)

        save_sheet(order, entries=self.entries(LIP_TRIGLICERIDOS="120"), user=self.tech)
        validate_results(order=order, user=self.bio)
        assert is_outdated(first, order)
        second, created = emit_report(order=order, user=self.tech)
        first.refresh_from_db()
        assert created and second.version == 2 and second.kind == "FINAL"
        assert first.status == Report.Status.REEMPLAZADO and first.replaced_at
        assert second.previous_hash == first.content_hash
        assert second.verification_code != first.verification_code

    def test_pdf_se_genera_con_firma_sello_y_logo(self):
        self.bio.signature_image = png()
        self.bio.stamp_image = png("darkred")
        self.bio.save()
        settings_obj = TenantSettings.get_solo()
        settings_obj.logo = png("teal")
        settings_obj.save()
        order = self.validated_lipids(extra=("TRIGLICERIDOS",))
        report, _ = emit_report(order=order, user=self.tech)
        assert report.payload["signers"][0]["signature"].startswith("firmas/")
        pdf = render_report_pdf(report, verify_url="https://lab.test/verificar/x/")
        assert pdf.startswith(b"%PDF") and len(pdf) > 5000


@override_settings(MEDIA_ROOT=MEDIA)
class ReportViewsTests(ReportTestBase):
    def setUp(self):
        super().setUp()
        seed_system_roles()
        Membership.objects.create(user=self.tech, role=Role.objects.get(code="TECNICO"))
        Membership.objects.create(user=self.bio, role=Role.objects.get(code="BIOANALISTA"))
        self.client = TenantClient(self.tenant)

    def test_emitir_ver_pdf_y_entregar(self):
        order = self.validated_lipids()
        self.client.force_login(self.tech)
        html = self.client.get("/informes/").content.decode()
        assert order.number in html and "Sin emitir" in html

        self.client.post(f"/informes/orden/{order.pk}/emitir/")
        report = Report.objects.get()
        response = self.client.get(f"/informes/orden/{order.pk}/version/{report.pk}.pdf")
        assert response["Content-Type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert "/verificar/" in self.client.get(f"/informes/orden/{order.pk}/").content.decode()

        self.client.post(f"/informes/orden/{order.pk}/entregar/")
        order.refresh_from_db()
        assert order.status == Order.Status.ENTREGADA and order.delivered_by == self.tech

    def test_no_se_entrega_una_orden_parcial(self):
        order = self.validated_lipids(extra=("TRIGLICERIDOS",))
        self.client.force_login(self.tech)
        self.client.post(f"/informes/orden/{order.pk}/entregar/")
        order.refresh_from_db()
        assert order.status != Order.Status.ENTREGADA
        assert Report.objects.get().kind == "PARCIAL"

    def test_verificacion_publica_sin_valores_y_con_plazo(self):
        order = self.validated_lipids()
        report, _ = emit_report(order=order, user=self.bio)
        anon = TenantClient(self.tenant)
        html = anon.get(f"/verificar/{report.verification_code}/").content.decode()
        assert "Informe auténtico" in html and report.content_hash in html
        assert ">210<" not in html and "COLESTEROL" not in html.upper().replace(
            "VERIFICACIÓN", "")
        assert anon.get(f"/verificar/{report.verification_code}/pdf/").status_code == 200

        Report.objects.filter(pk=report.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=31))
        html = anon.get(f"/verificar/{report.verification_code}/").content.decode()
        assert "venció" in html
        assert anon.get(f"/verificar/{report.verification_code}/pdf/").status_code == 404
        assert anon.get("/verificar/codigo-falso/").status_code == 404

    def test_version_reemplazada_avisa_y_no_descarga(self):
        order = self.validated_lipids(extra=("TRIGLICERIDOS",))
        old, _ = emit_report(order=order, user=self.bio)
        save_sheet(order, entries=self.entries(LIP_TRIGLICERIDOS="120"), user=self.tech)
        validate_results(order=order, user=self.bio)
        emit_report(order=order, user=self.bio)
        anon = TenantClient(self.tenant)
        html = anon.get(f"/verificar/{old.verification_code}/").content.decode()
        assert "reemplazado" in html and "versión 2" in html
        assert anon.get(f"/verificar/{old.verification_code}/pdf/").status_code == 404

    def test_pdf_interno_exige_sesion(self):
        order = self.validated_lipids()
        report, _ = emit_report(order=order, user=self.bio)
        response = TenantClient(self.tenant).get(
            f"/informes/orden/{order.pk}/version/{report.pk}.pdf")
        assert response.status_code == 302


class BrandTests(ReportTestBase):
    def test_firma_de_la_plataforma_editable(self):
        from apps.tenants.models import PlatformSettings
        from apps.tenants.services.platform import report_brand
        assert report_brand()["text"].startswith("Generado con Ordo Lab")
        platform = PlatformSettings.get_solo()
        platform.report_brand_contact = "@ordolab.ve"
        platform.save()
        assert report_brand()["contact"] == "@ordolab.ve"
        order = self.validated_lipids()
        report, _ = emit_report(order=order, user=self.bio)
        assert render_report_pdf(report, verify_url="https://x.test/v/").startswith(b"%PDF")
