import pytest
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenants.models import Tenant
from apps.tenants.services.provisioning import provision_tenant
from apps.tenants.services.suspension import reactivate_tenant, suspend_tenant


def _provision(schema_name: str) -> Tenant:
    tenant, _ = provision_tenant(
        name=f"Lab {schema_name}", schema_name=schema_name,
        subdomain=schema_name.replace("_", ""), admin_email=f"a@{schema_name}.test",
        seed_catalog=False,
    )
    return tenant


@pytest.mark.django_db(transaction=True)
def test_suspend_tenant_cambia_estado_y_anota_motivo():
    tenant = _provision("lab_susp12")
    try:
        suspend_tenant(tenant=tenant, by="Darwin", reason="Mora de 60 días")
        tenant.refresh_from_db()
        assert tenant.status == Tenant.Status.SUSPENDIDO
        assert "Mora de 60 días" in tenant.notes
        assert "Darwin" in tenant.notes
    finally:
        with schema_context(get_public_schema_name()):
            tenant.delete(force_drop=True)


@pytest.mark.django_db(transaction=True)
def test_suspend_tenant_sin_motivo_no_deja_dos_puntos_colgando():
    tenant = _provision("lab_susp12b")
    try:
        suspend_tenant(tenant=tenant, by="Darwin")
        tenant.refresh_from_db()
        assert tenant.status == Tenant.Status.SUSPENDIDO
        assert tenant.notes.splitlines()[-1].endswith("Suspendido por Darwin")
    finally:
        with schema_context(get_public_schema_name()):
            tenant.delete(force_drop=True)


@pytest.mark.django_db(transaction=True)
def test_reactivate_tenant_vuelve_a_activo():
    tenant = _provision("lab_react12")
    try:
        suspend_tenant(tenant=tenant, by="Darwin", reason="prueba")
        reactivate_tenant(tenant=tenant, by="Darwin")
        tenant.refresh_from_db()
        assert tenant.status == Tenant.Status.ACTIVO
        assert "Reactivado por Darwin" in tenant.notes
    finally:
        with schema_context(get_public_schema_name()):
            tenant.delete(force_drop=True)
