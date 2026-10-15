"""Métricas básicas del panel de plataforma (Fase 12). Nada se persiste: se calcula al
vuelo sobre `Tenant`/`Subscription`."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.tenants.models import Subscription, Tenant


def platform_metrics() -> dict:
    """{"total", "by_status" (dict código -> conteo, con las 5 claves siempre
    presentes), "trials_ending_soon" (laboratorios DEMO cuyo trial vence en 7 días,
    ordenados por vencimiento), "mrr_usd" (suma de `plan.price_monthly` de las
    suscripciones ACTIVA; no distingue moneda del plan — limitación conocida)}."""
    tenants = Tenant.objects.exclude(schema_name="public")

    counts = {code: 0 for code, _ in Tenant.Status.choices}
    for row in tenants.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]

    now = timezone.now()
    trials_ending_soon = tenants.filter(
        status=Tenant.Status.DEMO,
        trial_ends_at__isnull=False,
        trial_ends_at__gte=now,
        trial_ends_at__lte=now + timedelta(days=7),
    ).order_by("trial_ends_at")

    mrr = (
        Subscription.objects.filter(status=Subscription.Status.ACTIVA)
        .aggregate(total=Sum("plan__price_monthly"))["total"]
        or 0
    )

    return {
        "total": tenants.count(),
        "by_status": counts,
        "trials_ending_soon": list(trials_ending_soon),
        "mrr_usd": mrr,
    }
