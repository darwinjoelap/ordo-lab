from django.conf import settings
from django.shortcuts import resolve_url
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve
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

    def test_login_muestra_la_marca_y_el_laboratorio(self):
        """La pantalla partida: la marca del producto a un lado y, al otro, a qué
        laboratorio se está entrando. Sobre el panel azul marino va la variante
        blanca del símbolo, no la de color (el anillo marino desaparecería)."""
        body = self.client.get("/cuenta/login/").content.decode()
        assert "ordolab-mark-white.png" in body
        assert "css/ordolab.css" in body
        assert self.tenant.name in body

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


class DestinoTrasEntrarTests(SimpleTestCase):
    """`LOGIN_REDIRECT_URL` se resuelve contra el URLconf activo, y hay dos: el de los
    laboratorios y el del esquema `public`. Cuando era el nombre `tenant-home` —que sólo
    existe en el primero— entrar por el dominio de plataforma daba 500 por
    NoReverseMatch. Pasó inadvertido porque al panel se llega con ?next=/panel/, que
    evita el destino por defecto (2026-10-24)."""

    def test_resuelve_en_los_dos_esquemas(self):
        for urlconf in (settings.ROOT_URLCONF, settings.PUBLIC_SCHEMA_URLCONF):
            with self.subTest(urlconf=urlconf), override_settings(ROOT_URLCONF=urlconf):
                assert resolve_url(settings.LOGIN_REDIRECT_URL)

    @override_settings(ROOT_URLCONF=settings.PUBLIC_SCHEMA_URLCONF)
    def test_la_raiz_de_la_plataforma_lleva_al_panel(self):
        """Se llama la vista directamente: una petición completa pasaría por
        TenantMainMiddleware, que consulta la base, y aquí no hace falta."""
        vista = resolve("/").func
        response = vista(RequestFactory().get("/"))
        assert response.status_code == 302 and response["Location"] == "/panel/"
