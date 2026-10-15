from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from apps.tenants.services.suspension import suspend_tenant


class TenantAccessMiddlewareTests(TenantTestCase):
    """TenantTestCase (django_tenants.test.cases) crea self.tenant y ejecuta cada test
    dentro de su esquema — igual que apps/tenants/tests/test_isolation.py."""

    def setUp(self):
        super().setUp()
        self.client = TenantClient(self.tenant)

    def test_tenant_suspendido_bloquea_cualquier_pagina_incluido_el_login(self):
        suspend_tenant(tenant=self.tenant, by="Darwin", reason="prueba")

        response = self.client.get("/")
        assert response.status_code == 403
        assert b"suspendid" in response.content.lower()

        login_response = self.client.get("/cuenta/login/")
        assert login_response.status_code == 403

    def test_tenant_no_bloqueado_no_se_ve_afectado(self):
        # self.tenant nace en DEMO (no está en los estados bloqueados): la petición
        # sigue su curso normal (home redirige a login sin sesión).
        response = self.client.get("/")
        assert response.status_code in (200, 302)
