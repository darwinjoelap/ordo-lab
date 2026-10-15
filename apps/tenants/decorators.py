"""Acceso al panel de plataforma (Fase 12).

Decisión de Darwin (2026-10-08): sin modelo `PlatformUser` nuevo — reusa `accounts.User`
ya existente en el esquema `public` (SHARED_APP), marcado con `is_superuser=True`.
"""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def platform_required(view_func):
    """Exige sesión iniciada y `is_superuser=True`. Sin sesión, redirige al login
    (`accounts:login`, montado también en `public`); con sesión pero sin
    `is_superuser`, 403."""

    @wraps(view_func)
    def _checked(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Sólo el equipo de Biolife puede entrar aquí.")
        return view_func(request, *args, **kwargs)

    return login_required(_checked)
