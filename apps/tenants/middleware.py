"""Suspensión con efecto real (Fase 12, decisión de Darwin 2026-10-08): un laboratorio
en SUSPENDIDO/MOROSO/CANCELADO no entra a nada, ni siquiera al login — ve un aviso fijo
en cualquier URL de su dominio. Sus datos no se tocan ni se ocultan. El esquema `public`
(panel de plataforma) nunca se bloquea así.
"""
from __future__ import annotations

from django.shortcuts import render
from django_tenants.utils import get_public_schema_name

from apps.tenants.models import Tenant

_BLOCKED_STATUSES = {
    Tenant.Status.SUSPENDIDO,
    Tenant.Status.MOROSO,
    Tenant.Status.CANCELADO,
}
# Deben seguir sirviéndose aunque el tenant esté bloqueado: si no, la propia página
# de aviso se queda sin estilos (su <link rel="stylesheet"> también pasaría por aquí).
_EXEMPT_PREFIXES = ("/static/", "/media/", "/__debug__/")


class TenantAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if (
            tenant is not None
            and tenant.schema_name != get_public_schema_name()
            and tenant.status in _BLOCKED_STATUSES
            and not request.path.startswith(_EXEMPT_PREFIXES)
        ):
            return render(request, "tenants/suspendido.html", {"tenant": tenant}, status=403)
        return self.get_response(request)
