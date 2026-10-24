import pytest
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from apps.accounts.models import AuditLog, Membership, Role, User
from apps.accounts.services import lab_users as svc
from apps.accounts.services.user_management import seed_system_roles
from apps.core.exceptions import ApplicationError
from apps.settings_lab.models import TenantSettings


class LabPanelBase(TenantTestCase):
    def setUp(self):
        super().setUp()
        seed_system_roles()
        self.admin = User.objects.create_user(username="jefa", password="Clave-segura-1",
                                              first_name="Rosa", last_name="Díaz")
        Membership.objects.create(user=self.admin, role=Role.objects.get(code="ADMIN_LAB"))
        self.client = TenantClient(self.tenant)
        self.client.force_login(self.admin)


class LabUserServiceTests(LabPanelBase):
    def test_alta_con_clave_temporal_y_varios_roles(self):
        user, password = svc.create_lab_user(
            username="Maria", first_name="María", last_name="Gil",
            roles=["RECEPCION", "AUXILIAR_TOMA"], by=self.admin)
        assert user.username == "maria" and user.must_change_password
        assert len(password) == 10 and user.check_password(password)
        assert sorted(svc.role_codes(user)) == ["AUXILIAR_TOMA", "RECEPCION"]
        assert AuditLog.objects.filter(action="USUARIO_CREADO").exists()
        with pytest.raises(ApplicationError, match="ya existe"):
            svc.create_lab_user(username="MARIA", first_name="x", last_name="y",
                                roles=["RECEPCION"])
        with pytest.raises(ApplicationError, match="al menos un rol"):
            svc.create_lab_user(username="pedro", first_name="x", last_name="y", roles=[])

    def test_siempre_queda_un_administrador(self):
        with pytest.raises(ApplicationError, match="a sí mismo"):
            svc.update_lab_user(user=self.admin, data={}, roles=["BIOANALISTA"],
                                by=self.admin)
        with pytest.raises(ApplicationError, match="su propio usuario"):
            svc.set_active(user=self.admin, active=False, by=self.admin)
        other, _ = svc.create_lab_user(username="otro", first_name="O", last_name="T",
                                       roles=["BIOANALISTA"])
        with pytest.raises(ApplicationError, match="al menos un administrador"):
            svc.update_lab_user(user=self.admin, data={}, roles=["BIOANALISTA"], by=other)
        svc.update_lab_user(user=other, data={"professional_license": "MPPS 1"},
                            roles=["BIOANALISTA", "ADMIN_LAB"], by=self.admin)
        svc.update_lab_user(user=self.admin, data={}, roles=["BIOANALISTA"], by=other)
        assert svc.role_codes(self.admin) == ["BIOANALISTA"]
        other.refresh_from_db()
        assert other.professional_license == "MPPS 1"

    def test_cambio_de_clave_quita_la_obligacion(self):
        user, password = svc.create_lab_user(username="t", first_name="T", last_name="T",
                                             roles=["TECNICO"])
        with pytest.raises(ApplicationError, match="actual no es correcta"):
            svc.change_password(user=user, current="mala", new="Otra-clave-99")
        svc.change_password(user=user, current=password, new="Otra-clave-99")
        user.refresh_from_db()
        assert not user.must_change_password and user.check_password("Otra-clave-99")


class LabPanelViewsTests(LabPanelBase):
    def test_crear_usuario_muestra_la_clave_una_vez(self):
        response = self.client.post("/configuracion/usuarios/nuevo/", {
            "username": "aux1", "first_name": "Luis", "last_name": "Mora",
            "roles": ["AUXILIAR_TOMA"], "professional_title": ""})
        html = response.content.decode()
        user = User.objects.get(username="aux1")
        assert "no se volverá a mostrar" in html and user.must_change_password
        assert "Luis Mora" in self.client.get("/configuracion/usuarios/").content.decode()

    def test_clave_temporal_obliga_a_cambiarla(self):
        user, password = svc.create_lab_user(username="rec", first_name="R", last_name="R",
                                             roles=["RECEPCION"])
        client = TenantClient(self.tenant)
        client.force_login(user)
        response = client.get("/ordenes/")
        assert response.status_code == 302 and "/cuenta/clave/" in response["Location"]
        client.post("/cuenta/clave/", {"current": password, "new": "Nueva-clave-77",
                                       "repeat": "Nueva-clave-77"})
        assert client.get("/ordenes/").status_code == 200

    def test_solo_el_administrador_configura(self):
        tech = User.objects.create_user(username="tec", password="x")
        Membership.objects.create(user=tech, role=Role.objects.get(code="TECNICO"))
        client = TenantClient(self.tenant)
        client.force_login(tech)
        assert client.get("/configuracion/usuarios/").status_code == 403
        assert client.get("/configuracion/laboratorio/").status_code == 403
        html = client.get("/").content.decode()
        assert "Usuarios" not in html and "Resultados" in html
        assert client.get("/cuenta/perfil/").status_code == 200

    def test_datos_del_laboratorio(self):
        response = self.client.post("/configuracion/laboratorio/", {
            "phone": "0246-1234567", "email": "lab@x.test", "address": "Calle 1",
            "instagram": "@mi.lab", "website": "", "color_primary": "#1B5FA8",
            "lab_initials": "mlb", "report_footer_text": "", "report_disclaimer": "",
            "report_link_days": "15", "label_width_mm": "50", "label_height_mm": "25"})
        assert response.status_code == 302
        settings_obj = TenantSettings.get_solo()
        assert (settings_obj.instagram, settings_obj.lab_initials,
                settings_obj.report_link_days) == ("mi.lab", "MLB", 15)
        assert AuditLog.objects.filter(action="LABORATORIO_MODIFICADO").exists()
        html = self.client.get("/configuracion/laboratorio/").content.decode()
        assert "La cambia el administrador de Ordo Lab" in html

    def test_matriz_de_roles(self):
        html = self.client.get("/configuracion/roles/").content.decode()
        assert "Auxiliar de toma de muestras" in html and "Validar resultados" in html
