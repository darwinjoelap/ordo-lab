from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.exceptions import ApplicationError


class User(AbstractUser):
    """Usuario de un laboratorio (tenant). Aislado por esquema."""

    phone = models.CharField("Teléfono", max_length=30, blank=True, default="")
    professional_license = models.CharField(
        "Nº de colegiatura", max_length=40, blank=True, default=""
    )
    # Firma del informe (Fase 11, ADR-027): se imprime la de quien validó.
    professional_title = models.CharField(
        "Título profesional", max_length=60, blank=True, default="",
        help_text="Se imprime bajo la firma, p. ej. «Lcda. en Bioanálisis».",
    )
    signature_image = models.ImageField("Firma (imagen)", upload_to="firmas/", blank=True,
                                        null=True)
    stamp_image = models.ImageField("Sello (imagen)", upload_to="firmas/", blank=True,
                                    null=True)
    # Clave temporal puesta por el administrador del laboratorio (Fase 11b): obliga a
    # cambiarla en el primer ingreso.
    must_change_password = models.BooleanField("Debe cambiar la clave", default=False)
    # Usuario de soporte de Ordo Lab dentro del laboratorio (ADR-045). Se crea al
    # aprovisionar, **se ve en Configuración → Usuarios como cualquier otro** y el
    # laboratorio puede desactivarlo. La marca existe para poder nombrarlo en pantalla y
    # para no confundirlo con el personal del laboratorio en ningún conteo.
    is_support = models.BooleanField("Usuario de soporte de Ordo Lab", default=False)

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"


class Role(models.Model):
    class Code(models.TextChoices):
        ADMIN_LAB = "ADMIN_LAB", "Administrador del laboratorio"
        BIOANALISTA = "BIOANALISTA", "Bioanalista"
        TECNICO = "TECNICO", "Técnico"
        RECEPCION = "RECEPCION", "Recepción"
        FACTURACION = "FACTURACION", "Facturación"
        SOLO_LECTURA = "SOLO_LECTURA", "Sólo lectura"
        AUXILIAR_TOMA = "AUXILIAR_TOMA", "Auxiliar de toma de muestras"

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    name = models.CharField("Nombre", max_length=80)
    permissions = models.JSONField("Permisos", default=dict, blank=True)
    is_system = models.BooleanField("Rol del sistema", default=True)

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Membresía"
        verbose_name_plural = "Membresías"
        unique_together = [("user", "role")]

    def __str__(self) -> str:
        return f"{self.user} — {self.role}"


class AuditLog(models.Model):
    """Registro de auditoría append-only. Único punto de escritura: services/audit.py."""

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField("Acción", max_length=50)
    model_name = models.CharField("Modelo", max_length=100, blank=True, default="")
    object_id = models.CharField("ID del objeto", max_length=64, blank=True, default="")
    changes = models.JSONField("Cambios", null=True, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("User agent", max_length=255, blank=True, default="")
    created_at = models.DateTimeField("Creado el", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Registros de auditoría"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} — {self.user} — {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ApplicationError("AuditLog es append-only: no se puede modificar un registro.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ApplicationError("AuditLog es append-only: no se puede borrar un registro.")
