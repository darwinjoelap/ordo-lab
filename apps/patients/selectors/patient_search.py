from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q, QuerySet

from apps.patients.models import Patient, PatientAntecedent


def _with_antecedents(patients: QuerySet[Patient]) -> QuerySet[Patient]:
    """Antecedentes activos en `active_antecedents` (se muestran al elegir paciente)."""
    return patients.prefetch_related(Prefetch(
        "antecedents", queryset=PatientAntecedent.objects.filter(
            is_active=True, antecedent__is_active=True).select_related("antecedent"),
        to_attr="active_antecedents"))


def search_patients(*, query: str) -> QuerySet[Patient]:
    """Busca por código interno, número de documento, nombre o apellido.

    select_related en la localidad porque cualquier listado de resultados suele
    mostrarla junto al nombre del paciente.
    """
    query = query.strip()
    if not query:
        return Patient.objects.none()

    return _with_antecedents(Patient.objects.select_related("locality")).filter(
        # `unaccent` sólo en nombre y apellido: el código interno y el documento no
        # llevan tildes. Buscar "perez" tiene que encontrar a "Pérez" (ADR-040).
        Q(internal_code__icontains=query)
        | Q(document_number__icontains=query)
        | Q(first_name__unaccent__icontains=query)
        | Q(last_name__unaccent__icontains=query)
    )


def active_patients() -> QuerySet[Patient]:
    return Patient.objects.filter(is_active=True)


def get_patient(*, pk) -> Patient | None:
    try:
        return (_with_antecedents(Patient.objects.select_related("locality"))
                .filter(pk=pk, is_active=True).first())
    except (ValueError, ValidationError):  # id mal formado en la URL
        return None
