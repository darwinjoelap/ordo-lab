"""Configuración de la plataforma (esquema `public`) que usan los laboratorios."""
from __future__ import annotations

from apps.tenants.models import PlatformSettings


def report_brand() -> dict:
    """Firma de Ordo Lab al pie del informe: {"enabled", "text", "contact"}. Se lee al
    generar el PDF (no forma parte del contenido congelado del informe)."""
    platform = PlatformSettings.get_solo()
    return {"enabled": platform.report_brand_enabled,
            "text": platform.report_brand_text.strip(),
            "contact": platform.report_brand_contact.strip()}
