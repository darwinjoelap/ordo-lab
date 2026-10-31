"""Ficha del paciente, antecedentes y evolución (Fase 11e)."""
import datetime

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from apps.accounts.models import AuditLog, Membership, Role, User
from apps.accounts.services.user_management import seed_system_roles
from apps.catalog.models import Parameter, Test
from apps.catalog.services.seeding import seed_uroanalisis
from apps.catalog.services.seeding_containers import seed_containers
from apps.catalog.services.seeding_reference_ranges import seed_reference_ranges
from apps.core.charts import ChartPoint, chart_svg, line_chart, nice_ticks
from apps.orders.services.order_creation import create_order
from apps.orders.services.sample_collection import collect_all
from apps.orders.tests.factories import paciente
from apps.patients.models import Antecedent, Patient, PatientAntecedent, PatientGuardian
from apps.patients.services.patient_creation import register_patient
from apps.patients.services.seeding_antecedents import seed_antecedents
from apps.results.selectors.evolution import evolution_series
from apps.results.services.result_capture import save_sheet
from apps.results.services.validation import validate_results


class PatientBase(TenantTestCase):
    def setUp(self):
        super().setUp()
        seed_system_roles()
        seed_uroanalisis()
        seed_reference_ranges()
        seed_containers()
        seed_antecedents()
        self.users = {}
        for code in ("ADMIN_LAB", "RECEPCION", "BIOANALISTA", "AUXILIAR_TOMA"):
            user = User.objects.create_user(username=code.lower(), password="x")
            Membership.objects.create(user=user, role=Role.objects.get(code=code))
            self.users[code] = user
        self.patient = paciente(phone="0414-5551234")
        self.client = TenantClient(self.tenant)
        self.login("RECEPCION")

    def login(self, code):
        self.client.force_login(self.users[code])

    def glicemia(self, day: datetime.date, raw: str, *, validate: bool = True):
        order, _ = create_order(patient=self.patient,
                                tests=list(Test.objects.filter(code="GLICEMIA")))
        order.ordered_at = timezone.make_aware(datetime.datetime.combine(
            day, datetime.time(8)))
        order.save(update_fields=["ordered_at"])
        collect_all(order=order)
        param = Parameter.objects.get(code="QUIM_GLICEMIA")
        save_sheet(order, entries={str(param.pk): raw}, user=self.users["BIOANALISTA"])
        if validate:
            validate_results(order=order, user=self.users["BIOANALISTA"])
        return order


class ListAndEditTests(PatientBase):
    def test_lista_busca_por_nombre_y_telefono(self):
        paciente(first_name="Luis", last_name="Gómez", document_number="999",
                 sex=Patient.Sex.M)
        body = self.client.get("/pacientes/?q=maría pérez").content.decode()
        assert "Pérez, María" in body and "Gómez" not in body
        assert "Pérez, María" in self.client.get("/pacientes/?q=5551234").content.decode()
        self.login("AUXILIAR_TOMA")
        assert self.client.get("/pacientes/").status_code == 403

    def test_editar_conserva_la_edad_declarada_y_audita(self):
        declared_at = datetime.date(2020, 1, 1)
        patient = paciente(document_number="777", birth_date=None, declared_age_value=40,
                           declared_age_unit=Patient.AgeUnit.ANOS,
                           declared_age_at=declared_at)
        url = f"/pacientes/{patient.pk}/editar/"
        data = {k: v for k, v in self.client.get(url).context["form"].initial.items()
                if v is not None}
        data.update({"phone": "0412-0000000", "locality": ""})
        response = self.client.post(url, data)
        patient.refresh_from_db()
        assert response.status_code == 302
        assert patient.phone == "0412-0000000" and patient.declared_age_at == declared_at
        assert AuditLog.objects.filter(action="PACIENTE_MODIFICADO").exists()

    def test_documento_repetido_no_se_guarda(self):
        other = paciente(document_number="555")
        url = f"/pacientes/{other.pk}/editar/"
        data = {k: v for k, v in self.client.get(url).context["form"].initial.items()
                if v is not None}
        data.update({"document_number": "12345678", "locality": ""})
        response = self.client.post(url, data)
        assert "Ya existe otro paciente" in response.content.decode()


class GuardianTests(PatientBase):
    def test_menor_sin_documento_conserva_un_representante(self):
        child = register_patient(
            first_name="Ana", last_name="Pérez", sex="F", document_type="SIN_DOCUMENTO",
            birth_date=datetime.date(2022, 1, 1),
            guardian_data={"document_type": "V", "document_number": "12345678",
                           "first_name": "María", "last_name": "Pérez",
                           "relationship": "MADRE"})
        first = child.guardians.get()
        url = f"/pacientes/{child.pk}/representantes/{first.pk}/retirar/"
        response = self.client.post(url, follow=True)
        assert "debe conservar" in response.content.decode()
        first.refresh_from_db()
        assert first.is_active

        self.client.post(f"/pacientes/{child.pk}/representantes/nuevo/", {
            "document_type": "V", "document_number": "8888", "first_name": "José",
            "last_name": "Pérez", "relationship": "PADRE"})
        self.client.post(url)
        first.refresh_from_db()
        father = PatientGuardian.objects.get(patient=child, guardian__document_number="8888")
        assert not first.is_active and father.is_primary


class AntecedentTests(PatientBase):
    def test_agregar_quitar_y_ver_en_la_orden(self):
        diabetes = Antecedent.objects.get(code="DIABETES")
        assert diabetes.suggested_parameters.filter(code="QUIM_GLICEMIA").exists()
        self.client.post(f"/pacientes/{self.patient.pk}/antecedentes/",
                         {"antecedent": diabetes.pk, "notes": "tipo 2"})
        link = PatientAntecedent.objects.get(patient=self.patient)
        assert link.created_by == self.users["RECEPCION"]
        order = self.glicemia(datetime.date(2026, 5, 1), "130")
        assert "Diabetes" in self.client.get(f"/ordenes/{order.pk}/").content.decode()

        self.client.post(f"/pacientes/{self.patient.pk}/antecedentes/{link.pk}/retirar/")
        link.refresh_from_db()
        assert not link.is_active
        self.client.post(f"/pacientes/{self.patient.pk}/antecedentes/",
                         {"antecedent": diabetes.pk})
        link.refresh_from_db()
        assert link.is_active and PatientAntecedent.objects.count() == 1

    def test_tabla_auxiliar_de_antecedentes(self):
        self.login("BIOANALISTA")
        assert self.client.get("/tablas/antecedentes/").status_code == 200
        self.login("RECEPCION")
        diabetes = Antecedent.objects.get(code="DIABETES")
        assert self.client.post(f"/tablas/antecedentes/{diabetes.pk}/",
                                {"code": "X"}).status_code == 403


class EvolutionTests(PatientBase):
    def setUp(self):
        super().setUp()
        for day, raw in ((datetime.date(2026, 1, 10), "95"),
                         (datetime.date(2026, 4, 10), "126"),
                         (datetime.date(2026, 7, 10), "140")):
            self.glicemia(day, raw)
        self.glicemia(datetime.date(2026, 8, 10), "300", validate=False)
        self.param = Parameter.objects.get(code="QUIM_GLICEMIA")

    def test_serie_solo_validados_con_variacion(self):
        (series,) = (s for s in evolution_series(patient=self.patient)
                     if s["parameter"].code == "QUIM_GLICEMIA")
        points = series["points"]
        assert [int(p.value) for p in points] == [95, 126, 140]
        assert points[0].delta_pct is None and round(points[1].delta_pct, 1) == 32.6
        assert points[-1].flag in ("ALTO", "CRITICO_ALTO")

    def test_ficha_y_evolucion_muestran_la_tendencia(self):
        PatientAntecedent.objects.create(patient=self.patient,
                                         antecedent=Antecedent.objects.get(code="DIABETES"))
        body = self.client.get(f"/pacientes/{self.patient.pk}/").content.decode()
        assert "GLICEMIA" in body and "vigilar" in body and "class=\"spark\"" in body
        assert "Hemoglobina glicada" in body  # sugerido sin resultados aún
        body = self.client.get(f"/pacientes/{self.patient.pk}/evolucion/"
                               f"?p={self.param.pk}").content.decode()
        assert body.count("<circle class=\"chart__pt") == 3 and "chart__band" in body
        assert "+32,6 %" in body
        # Acotado a la tabla y buscando la celda, no el número suelto: `split("<table")[1]`
        # llegaba hasta el final del documento e incluía el panel lateral de parámetros,
        # donde un UUID con `300` dentro hacía fallar la prueba al azar (2026-10-30:
        # `...b0a6-9913a300a76d`). Mismo idioma que `test_reports.py` con `">210<"`.
        tabla = body.split("<table")[1].split("</table>")[0]
        assert ">300<" not in tabla, "un resultado sin validar no entra a la evolución"

    def test_pdf_de_evolucion(self):
        url = f"/pacientes/{self.patient.pk}/evolucion/pdf/"
        response = self.client.get(url, {"p": [str(self.param.pk), "no-es-uuid"]})
        assert response["Content-Type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert self.client.get(url, {"p": "no-es-uuid"}).status_code == 302

    def test_valor_anterior_con_variacion_al_cargar(self):
        order, _ = create_order(patient=self.patient,
                                tests=list(Test.objects.filter(code="GLICEMIA")))
        collect_all(order=order)
        save_sheet(order, entries={str(self.param.pk): "154"}, user=self.users["BIOANALISTA"])
        self.login("BIOANALISTA")
        body = self.client.get(f"/resultados/orden/{order.pk}/").content.decode()
        assert f"evolucion/?p={self.param.pk}" in body and "+10,0 %" in body


class ChartTests(TenantTestCase):
    def test_marcas_redondas_y_un_solo_punto(self):
        assert nice_ticks(95, 140) == [80, 100, 120, 140]
        chart = line_chart([ChartPoint(when=datetime.date(2026, 1, 1), value=5.0,
                                       low=4.0, high=6.0, label="<x>")])
        svg = chart_svg(chart)
        assert svg.count("<circle") == 1 and "&lt;x&gt;" in svg and len(chart.bands) == 1
