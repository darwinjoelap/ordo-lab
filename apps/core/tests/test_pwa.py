"""Fase 13 (PWA base y modo lectura offline): el service worker, el manifest y la
página de respaldo deben servirse sin exigir sesión — si quedaran detrás de
@login_required, el navegador cachearía la redirección al login en vez del recurso
real."""
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient


class ServiceWorkerTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def test_sw_js_responde_sin_sesion_con_content_type_javascript(self):
        response = self.client.get(reverse("core:service-worker"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/javascript")

    def test_sw_js_no_intercepta_la_pagina_de_login(self):
        """La ruta "/ordenes/" puede cachearse, pero el service worker nunca debe
        cachear navegaciones de login ni acciones (ver EXCLUDED_PATH_PARTS)."""
        response = self.client.get(reverse("core:service-worker"))

        body = response.content.decode()
        assert "/ordenes/" in body
        assert "/pacientes/" in body
        assert "/nueva/" in body  # ruta de acción excluida, nunca cacheada


class ManifestTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def test_manifest_responde_sin_sesion_con_content_type_de_manifest(self):
        response = self.client.get(reverse("core:manifest"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/manifest+json")

    def test_manifest_incluye_el_nombre_del_laboratorio(self):
        response = self.client.get(reverse("core:manifest"))

        assert self.tenant.name in response.content.decode()


class OfflinePageTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def test_offline_responde_sin_sesion(self):
        response = self.client.get(reverse("core:offline"))

        assert response.status_code == 200
        assert "Sin conexión" in response.content.decode()
