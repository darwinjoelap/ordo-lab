from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import ApplicationError
from apps.masterdata.models import Locality
from apps.patients.models import Guardian, Patient, PatientCodeSequence, PatientGuardian
from apps.patients.services.guardian_linking import create_guardian, link_guardian
from apps.settings_lab.models import TenantSettings


def generate_internal_code() -> str:
    """Genera el siguiente internal_code del año actual: {YY}{iniciales}{correlativo6}.

    El correlativo reinicia en 1 cada año (el año va embebido en el propio código).
    Usa select_for_update() sobre PatientCodeSequence para que dos registros
    simultáneos nunca obtengan el mismo correlativo.
    """
    lab_initials = TenantSettings.get_solo().lab_initials
    if not lab_initials:
        raise ApplicationError(
            "El laboratorio todavía no tiene siglas, y forman parte del número de "
            "historia de cada paciente (por ejemplo 26LDU000001). Configúrelas en "
            "Configuración → Datos del laboratorio → Siglas del laboratorio."
        )

    year = timezone.localdate().year
    with transaction.atomic():
        sequence, _ = PatientCodeSequence.objects.select_for_update().get_or_create(
            year=year
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        correlative = sequence.last_value

    year_terminal = str(year)[-2:]
    return f"{year_terminal}{lab_initials}{correlative:06d}"


def _validate_document(*, document_type: str, document_number: str | None) -> None:
    if document_type == Patient.DocumentType.SIN_DOCUMENTO:
        if document_number:
            raise ApplicationError(
                "Un paciente sin documento no puede tener número de documento."
            )
    elif not document_number:
        raise ApplicationError(
            "El número de documento es obligatorio para el tipo de documento elegido."
        )


def create_patient(
    *,
    first_name: str,
    last_name: str,
    sex: str,
    document_type: str,
    document_number: str | None = None,
    birth_date: date | None = None,
    declared_age_value: int | None = None,
    declared_age_unit: str = "",
    declared_age_at: date | None = None,
    locality: Locality | None = None,
    address: str = "",
    phone: str = "",
    email: str = "",
    created_by: User | None = None,
    guardian: Guardian | None = None,
    guardian_relationship: str = "",
    guardian_relationship_detail: str = "",
) -> Patient:
    """Crea un paciente. Si es menor de 18 años y no tiene document_number, exige un
    representante (guardian + guardian_relationship) en la misma llamada — todo dentro
    de una única transacción, para no dejar pacientes "a medias" sin representante."""
    document_number = document_number or None
    _validate_document(document_type=document_type, document_number=document_number)

    if birth_date is None and declared_age_value is None:
        raise ApplicationError(
            "Debe indicarse la fecha de nacimiento o una edad declarada."
        )

    if guardian is not None:
        if not guardian_relationship:
            raise ApplicationError(
                "Debe indicarse el parentesco del representante (guardian_relationship)."
            )
        if (
            guardian_relationship == PatientGuardian.Relationship.OTRO
            and not guardian_relationship_detail
        ):
            raise ApplicationError(
                "Debe especificarse el detalle del parentesco cuando la relación es 'Otro'."
            )

    try:
        with transaction.atomic():
            patient = Patient(
                internal_code=generate_internal_code(),
                first_name=first_name,
                last_name=last_name,
                sex=sex,
                document_type=document_type,
                document_number=document_number,
                birth_date=birth_date,
                declared_age_value=declared_age_value,
                declared_age_unit=declared_age_unit,
                declared_age_at=declared_age_at,
                locality=locality,
                address=address,
                phone=phone,
                email=email,
                created_by=created_by,
            )

            requires_guardian = patient.is_minor and not document_number
            if requires_guardian and guardian is None:
                raise ApplicationError(
                    "El paciente es menor de edad y no tiene documento propio: "
                    "requiere un representante legal."
                )

            patient.save()

            if guardian is not None:
                link_guardian(
                    patient=patient,
                    guardian=guardian,
                    relationship=guardian_relationship,
                    relationship_detail=guardian_relationship_detail,
                    is_primary=True,
                )
    except IntegrityError as exc:
        raise ApplicationError(
            "Ya existe un paciente registrado con ese tipo y número de documento."
        ) from exc

    return patient


def register_patient(*, guardian_data: dict | None = None, created_by: User | None = None,
                     **patient_data) -> Patient:
    """Registro desde la recepción (Fase 09): paciente y, si se indica, su representante,
    en una sola transacción. Reutiliza el representante si ya existe con ese documento."""
    with transaction.atomic():
        guardian = None
        relationship = relationship_detail = ""
        if guardian_data:
            data = dict(guardian_data)
            relationship = data.pop("relationship")
            relationship_detail = data.pop("relationship_detail", "")
            guardian = Guardian.objects.filter(
                document_type=data["document_type"], document_number=data["document_number"]
            ).first() or create_guardian(**data)
        return create_patient(
            guardian=guardian, guardian_relationship=relationship,
            guardian_relationship_detail=relationship_detail, created_by=created_by,
            **patient_data,
        )
