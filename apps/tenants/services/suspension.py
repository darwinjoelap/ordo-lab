"""Suspender/reactivar un laboratorio (Fase 12). Sin modelo de auditoría nuevo: queda
anotado en `Tenant.notes`, que ya existía. El efecto real (bloquear el acceso) lo aplica
`apps.tenants.middleware.TenantAccessMiddleware` leyendo `Tenant.status`."""
from __future__ import annotations

from django.utils import timezone

from apps.tenants.models import Tenant


def _stamp() -> str:
    return timezone.now().strftime("%Y-%m-%d %H:%M")


def suspend_tenant(*, tenant: Tenant, by: str, reason: str = "") -> Tenant:
    """Pasa el laboratorio a SUSPENDIDO. No borra ni oculta ningún dato."""
    tenant.status = Tenant.Status.SUSPENDIDO
    note = f"[{_stamp()}] Suspendido por {by}" + (f": {reason}" if reason else "")
    tenant.notes = f"{tenant.notes}\n{note}".strip()
    tenant.save(update_fields=["status", "notes"])
    return tenant


def reactivate_tenant(*, tenant: Tenant, by: str) -> Tenant:
    """Pasa el laboratorio a ACTIVO. Úsese también para levantar un MOROSO o un
    CANCELADO que vuelve a pagar."""
    tenant.status = Tenant.Status.ACTIVO
    note = f"[{_stamp()}] Reactivado por {by}"
    tenant.notes = f"{tenant.notes}\n{note}".strip()
    tenant.save(update_fields=["status", "notes"])
    return tenant
