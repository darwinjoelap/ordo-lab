from datetime import date

from django.db import models
from django.utils import timezone

from apps.core.models import TenantBaseModel


class Patient(TenantBaseModel):
    class DocumentType(models.TextChoices):
        V = "V", "Cédula V"
        E = "E", "Cédula E"
        J = "J", "RIF Jurídico"
        P = "P", "Pasaporte"
        SIN_DOCUMENTO = "SIN_DOCUMENTO", "Sin documento"

    class Sex(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"

    class AgeUnit(models.TextChoices):
        DIAS = "DIAS", "Días"
        MESES = "MESES", "Meses"
        ANOS = "ANOS", "Años"

    internal_code = models.CharField(
        "Código interno", max_length=20, unique=True, editable=False
    )
    document_type = models.CharField(
        "Tipo de documento", max_length=15, choices=DocumentType.choices
    )
    # null=True intencional (excepción documentada, ver docs/03_CONVENCIONES.md):
    # habilita UniqueConstraint(condition=Q(document_number__isnull=False)).
    document_number = models.CharField(  # noqa: DJ001
        "Número de documento", max_length=20, null=True, blank=True
    )
    first_name = models.CharField("Nombres", max_length=100)
    last_name = models.CharField("Apellidos", max_length=100)
    sex = models.CharField("Sexo", max_length=1, choices=Sex.choices)
    birth_date = models.DateField("Fecha de nacimiento", null=True, blank=True)
    declared_age_value = models.PositiveIntegerField(
        "Edad declarada", null=True, blank=True
    )
    declared_age_unit = models.CharField(
        "Unidad de edad declarada", max_length=5, choices=AgeUnit.choices,
        blank=True, default="",
    )
    declared_age_at = models.DateField(
        "Fecha en que se declaró la edad", null=True, blank=True
    )
    locality = models.ForeignKey(
        "masterdata.Locality", verbose_name="Localidad",
        on_delete=models.PROTECT, null=True, blank=True,
    )
    address = models.CharField("Dirección", max_length=255, blank=True, default="")
    phone = models.CharField("Teléfono", max_length=30, blank=True, default="")
    email = models.EmailField("Correo", blank=True, default="")
    # Sincronización offline (Fase 14): id de la mutación que lo creó sin conexión.
    # Único, así reenviar la cola no duplica el paciente. Vacío si se registró en línea.
    client_mutation_id = models.UUIDField("Id de la mutación offline", null=True,
                                           blank=True, unique=True)

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "document_number"],
                condition=models.Q(document_number__isnull=False),
                name="uniq_patient_document",
            ),
            models.CheckConstraint(
                condition=models.Q(birth_date__isnull=False)
                | models.Q(declared_age_value__isnull=False),
                name="patient_has_birth_date_or_declared_age",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.internal_code})"

    def age_in_years(self, *, as_of: date | None = None) -> int:
        """Edad aproximada en años completos — sólo para la regla de mayoría de edad
        (Fase 04). No usar para resolución de rangos de referencia: eso requiere edad
        exacta en días y es responsabilidad de la Fase 06."""
        as_of = as_of or timezone.localdate()
        if self.birth_date is not None:
            years = as_of.year - self.birth_date.year
            if (as_of.month, as_of.day) < (self.birth_date.month, self.birth_date.day):
                years -= 1
            return years

        base = self.declared_age_at or as_of
        elapsed_years = (as_of - base).days / 365.25
        value = self.declared_age_value or 0
        if self.declared_age_unit == self.AgeUnit.ANOS:
            return int(value + elapsed_years)
        if self.declared_age_unit == self.AgeUnit.MESES:
            return int((value / 12) + elapsed_years)
        return int((value / 365.25) + elapsed_years)

    @property
    def is_minor(self) -> bool:
        return self.age_in_years() < 18


class Guardian(TenantBaseModel):
    """Representante o tutor legal. Debe estar siempre identificado con documento."""

    DOCUMENT_TYPE_CHOICES = [
        (Patient.DocumentType.V, Patient.DocumentType.V.label),
        (Patient.DocumentType.E, Patient.DocumentType.E.label),
        (Patient.DocumentType.J, Patient.DocumentType.J.label),
        (Patient.DocumentType.P, Patient.DocumentType.P.label),
    ]

    document_type = models.CharField(
        "Tipo de documento", max_length=1, choices=DOCUMENT_TYPE_CHOICES
    )
    document_number = models.CharField("Número de documento", max_length=20)
    first_name = models.CharField("Nombres", max_length=100)
    last_name = models.CharField("Apellidos", max_length=100)
    phone = models.CharField("Teléfono", max_length=30, blank=True, default="")
    address = models.CharField("Dirección", max_length=255, blank=True, default="")
    email = models.EmailField("Correo", blank=True, default="")

    class Meta:
        verbose_name = "Representante"
        verbose_name_plural = "Representantes"
        unique_together = [("document_type", "document_number")]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"


class PatientGuardian(TenantBaseModel):
    class Relationship(models.TextChoices):
        MADRE = "MADRE", "Madre"
        PADRE = "PADRE", "Padre"
        ABUELO = "ABUELO", "Abuelo/a"
        TIO = "TIO", "Tío/a"
        HERMANO = "HERMANO", "Hermano/a"
        TUTOR_LEGAL = "TUTOR_LEGAL", "Tutor legal"
        OTRO = "OTRO", "Otro"

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="guardians"
    )
    guardian = models.ForeignKey(
        Guardian, on_delete=models.PROTECT, related_name="patients"
    )
    relationship = models.CharField(
        "Parentesco", max_length=15, choices=Relationship.choices
    )
    relationship_detail = models.CharField(
        "Detalle del parentesco", max_length=100, blank=True, default=""
    )
    is_primary = models.BooleanField("Representante principal", default=True)
    legal_doc_ref = models.CharField(
        "Referencia de documento legal", max_length=100, blank=True, default=""
    )

    class Meta:
        verbose_name = "Representante de paciente"
        verbose_name_plural = "Representantes de pacientes"
        unique_together = [("patient", "guardian")]

    def __str__(self) -> str:
        return f"{self.guardian} — {self.patient} ({self.get_relationship_display()})"


class PatientCodeSequence(models.Model):
    """Contador de internal_code por año. No hereda TenantBaseModel: es plumbing
    interno, mismo criterio que Role/Membership/AuditLog en apps.accounts."""

    year = models.PositiveIntegerField("Año", unique=True)
    last_value = models.PositiveIntegerField("Último valor usado", default=0)

    class Meta:
        verbose_name = "Secuencia de código de paciente"
        verbose_name_plural = "Secuencias de código de paciente"

    def __str__(self) -> str:
        return f"{self.year}: {self.last_value}"


class Antecedent(TenantBaseModel):
    """Antecedente clínico que el laboratorio quiere vigilar (Fase 11e, ADR-032):
    diabetes, hipertensión, anticoagulado… Cada uno sugiere qué parámetros seguir en la
    evolución del paciente. Lo configura cada laboratorio (tabla auxiliar)."""

    code = models.CharField("Código", max_length=30, unique=True)
    name = models.CharField("Nombre", max_length=80)
    description = models.CharField("Descripción", max_length=255, blank=True, default="")
    suggested_parameters = models.ManyToManyField(
        "catalog.Parameter", blank=True, related_name="+",
        verbose_name="Parámetros a vigilar",
    )
    order_index = models.PositiveIntegerField("Orden", default=0)

    class Meta:
        verbose_name = "Antecedente"
        verbose_name_plural = "Antecedentes"
        ordering = ["order_index", "name"]

    def __str__(self) -> str:
        return self.name


class PatientAntecedent(TenantBaseModel):
    """Antecedente registrado a un paciente: quién (`created_by`) y cuándo
    (`created_at`). No se borra: si deja de aplicar se desactiva."""

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,
                                related_name="antecedents")
    antecedent = models.ForeignKey(Antecedent, on_delete=models.PROTECT,
                                   related_name="patients", verbose_name="Antecedente")
    notes = models.CharField("Nota", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "Antecedente del paciente"
        verbose_name_plural = "Antecedentes del paciente"
        ordering = ["antecedent__order_index", "antecedent__name"]
        constraints = [
            models.UniqueConstraint(fields=["patient", "antecedent"],
                                    name="patientantecedent_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.patient} — {self.antecedent}"
