import pytest
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenants.models import Subscription, Tenant
from apps.tenants.services.metrics import platform_metrics
from apps.tenants.services.provisioning import provision_tenant


@pytest.mark.django_db(transaction=True)
def test_platform_metrics_cuenta_por_estado_y_excluye_public():
    tenant, _ = provision_tenant(
        name="Lab Métricas", schema_name="lab_metricas12", subdomain="labmetricas12",
        admin_email="a@labmetricas12.test", seed_catalog=False,
    )
    try:
        metrics = platform_metrics()
        assert metrics["total"] >= 1
        assert metrics["by_status"][Tenant.Status.DEMO] >= 1
        assert set(metrics["by_status"]) == {c for c, _ in Tenant.Status.choices}
    finally:
        with schema_context(get_public_schema_name()):
            tenant.delete(force_drop=True)


@pytest.mark.django_db(transaction=True)
def test_platform_metrics_mrr_suma_solo_suscripciones_activas(plan_basico):
    # El fixture puede traer price_monthly tal cual se lo pasaron al crearlo (p. ej. un
    # str) sin recastear: Django no coacciona el atributo en memoria por asignarlo, sólo
    # al escribirlo en la base. Se refresca para comparar siempre contra un Decimal real.
    plan_basico.refresh_from_db()

    tenant, _ = provision_tenant(
        name="Lab MRR", schema_name="lab_mrr12", subdomain="labmrr12",
        admin_email="a@labmrr12.test", plan=plan_basico, seed_catalog=False,
    )
    try:
        with schema_context(get_public_schema_name()):
            sub = Subscription.objects.get(tenant=tenant, plan=plan_basico)
            sub.status = Subscription.Status.ACTIVA
            sub.save(update_fields=["status"])

        before = platform_metrics()["mrr_usd"]
        assert before >= plan_basico.price_monthly

        with schema_context(get_public_schema_name()):
            sub.status = Subscription.Status.CANCELADA
            sub.save(update_fields=["status"])

        after = platform_metrics()["mrr_usd"]
        assert after == before - plan_basico.price_monthly
    finally:
        with schema_context(get_public_schema_name()):
            tenant.delete(force_drop=True)
