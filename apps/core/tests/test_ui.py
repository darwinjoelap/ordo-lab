from django.template import Context, Template
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from apps.accounts.models import User
from apps.core.templatetags.ui import initials


class PantallasBaseTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)
        self.staff = User.objects.create_user(
            username="ana", password="x", first_name="Ana", last_name="Rivas", is_staff=True
        )
        self.tecnico = User.objects.create_user(username="tec", password="x")

    def test_login_muestra_la_marca(self):
        body = self.client.get("/cuenta/login/").content.decode()
        assert "ordolab-mark-96.png" in body and "css/ordolab.css" in body

    def test_inicio_exige_sesion(self):
        response = self.client.get("/")
        assert response.status_code == 302 and "/cuenta/login/" in response["Location"]

    def test_inicio_con_sesion_usa_la_estructura_de_la_app(self):
        self.client.force_login(self.staff)
        body = self.client.get("/").content.decode()
        assert 'class="sidebar"' in body and "Hola, Ana" in body
        assert "Guía de estilo" in body  # sólo para el staff de Ordo Lab

    def test_usuario_sin_staff_no_ve_configuracion_ni_guia(self):
        self.client.force_login(self.tecnico)
        body = self.client.get("/").content.decode()
        assert "Guía de estilo" not in body
        assert self.client.get("/estilo/").status_code == 302

    def test_guia_de_estilo(self):
        self.client.force_login(self.staff)
        response = self.client.get("/estilo/", {"first_name": ""})
        body = response.content.decode()
        assert response.status_code == 200
        assert "flag--critico" in body and "form-grid" in body
        assert "has-error" in body  # el ejemplo muestra errores de validación


class EtiquetasUiTests(TenantTestCase):
    def test_iniciales(self):
        assert initials(User(first_name="Darwin", last_name="Arroyo")) == "DA"
        assert initials(User(username="tec")) == "T"

    def test_icono(self):
        html = Template('{% load ui %}{% icon "house" %}').render(Context())
        assert '<use href="#i-house">' in html
