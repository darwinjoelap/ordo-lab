"""Contenido congelado del informe (Fase 11, ADR-027).

`build_payload()` junta todo lo que se imprime —laboratorio, paciente, orden, exámenes
**validados** con su referencia congelada y observaciones, firmantes— en un dict JSON.
`content_hash()` es la huella SHA-256 de ese dict en forma canónica: si nada cambió, la
huella es la misma y no se emite una versión nueva.

Las imágenes (logo, firma, sello) se guardan por **ruta de archivo**: al subir una firma
nueva se crea otro archivo, así un informe viejo sigue mostrando la firma con la que se
emitió y la huella cubre qué imagen se usó.
"""
from __future__ import annotations

import hashlib
import json

from django.db import connection
from django.utils import timezone

from apps.orders.selectors.order_queries import report_order_facts
from apps.patients.services.patient_age import patient_age_text
from apps.results.selectors.result_queries import report_results
from apps.settings_lab.models import TenantSettings

SCHEMA = 1


def _iso(value) -> str:
    return timezone.localtime(value).isoformat() if value else ""


def _file(field) -> str:
    return field.name if field else ""


def _lab(settings_obj: TenantSettings) -> dict:
    tenant = getattr(connection, "tenant", None)
    return {
        "name": getattr(tenant, "name", "") or "",
        "legal_name": getattr(tenant, "legal_name", "") or "",
        "rif": getattr(tenant, "rif", "") or "",
        "phone": settings_obj.phone, "address": settings_obj.address,
        "email": settings_obj.email, "instagram": settings_obj.instagram,
        "website": settings_obj.website, "logo": _file(settings_obj.logo),
        "color": settings_obj.color_primary or "#1B5FA8",
        # Texto propio del laboratorio al pie (opcional; sin valor por defecto).
        "footer": settings_obj.report_footer_text.strip(),
        "disclaimer": settings_obj.report_disclaimer.strip(),
    }


def _patient(order) -> dict:
    patient = order.patient
    document = (f"{patient.document_type}-{patient.document_number}"
                if patient.document_number else "")
    return {
        "name": f"{patient.first_name} {patient.last_name}".strip(),
        "first_name": patient.first_name, "last_name": patient.last_name,
        "document": document, "code": patient.internal_code,
        "sex": patient.get_sex_display(),
        "age": patient_age_text(patient, as_of=timezone.localdate(order.ordered_at)),
        "birth_date": patient.birth_date.isoformat() if patient.birth_date else "",
        "phone": patient.phone, "address": patient.address,
    }


def _signer(user) -> dict:
    return {
        "id": str(user.pk), "name": user.get_full_name() or user.get_username(),
        "title": user.professional_title, "license": user.professional_license,
        "signature": _file(user.signature_image), "stamp": _file(user.stamp_image),
    }


def build_payload(order) -> dict:
    """Contenido del informe con lo validado hoy. `kind` = FINAL si no queda ningún
    examen vigente sin validar."""
    settings_obj = TenantSettings.get_solo()
    facts = report_order_facts(order=order)
    blocks = report_results(order=order)

    sections: list[dict] = []
    signers: dict[str, dict] = {}
    for block in blocks:
        if not sections or sections[-1]["name"] != block["section"]:
            sections.append({"name": block["section"], "page_break": block["page_break"],
                             "tests": []})
        user = block["validated_by"]
        if user is not None and str(user.pk) not in signers:
            signers[str(user.pk)] = _signer(user)
        test = {
            "code": block["code"], "name": block["name"], "method": block["method"],
            "validated_at": _iso(block["validated_at"]),
            "validated_by": str(user.pk) if user else "",
            "observations": block["observations"], "rows": block["rows"],
        }
        # Fase 15: la clave `amended` sólo se agrega cuando el examen fue rectificado.
        # Omitirla cuando no lo fue mantiene la huella idéntica a la que ya tenían los
        # informes emitidos, así ninguno queda marcado como desactualizado por esta
        # fase. El motivo NO entra al payload a propósito: es interno, no se imprime.
        if block.get("amended"):
            test["amended"] = True
        sections[-1]["tests"].append(test)

    return {
        "schema": SCHEMA,
        "kind": "PARCIAL" if facts["pending_tests"] else "FINAL",
        "lab": _lab(settings_obj),
        "patient": _patient(order),
        "order": {
            "id": str(order.pk), "number": order.number,
            "ordered_at": _iso(order.ordered_at), "collected_at": _iso(facts["collected_at"]),
            "requested_by": order.requested_by,
            "condition": (order.get_patient_condition_display()
                          if order.patient_condition != "NINGUNA" else ""),
        },
        "sections": sections,
        "pending_tests": facts["pending_tests"],
        "signers": list(signers.values()),
        "test_count": sum(len(s["tests"]) for s in sections),
        **({"amended_tests": amended} if (amended := [
            t["name"] for section in sections for t in section["tests"]
            if t.get("amended")]) else {}),
    }


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def content_hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def lab_info() -> dict:
    """Datos del laboratorio para otros documentos (p. ej. la evolución, Fase 11e)."""
    return _lab(TenantSettings.get_solo())
