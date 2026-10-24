from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(TenantMixin):
    class Status(models.TextChoices):
        DEMO = "DEMO", "Demo"
        ACTIVO = "ACTIVO", "Activo"
        SUSPENDIDO = "SUSPENDIDO", "Suspendido"
        MOROSO = "MOROSO", "Moroso"
        CANCELADO = "CANCELADO", "Cancelado"

    name = models.CharField("Nombre del laboratorio", max_length=200)
    legal_name = models.CharField("Razón social", max_length=200, blank=True, default="")
    rif = models.CharField("RIF", max_length=20, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DEMO)
    onboarded_at = models.DateTimeField(auto_now_add=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    auto_create_schema = True
    auto_drop_schema = False   # NUNCA True: un delete accidental borraría datos clínicos (ADR-003)

    class Meta:
        verbose_name = "Laboratorio"
        verbose_name_plural = "Laboratorios"

    def __str__(self) -> str:
        return self.name


class Domain(DomainMixin):
    class Meta:
        verbose_name = "Dominio"
        verbose_name_plural = "Dominios"


class Plan(models.Model):
    code = models.CharField("Código", max_length=30, unique=True)
    name = models.CharField("Nombre", max_length=100)
    price_monthly = models.DecimalField("Precio mensual", max_digits=10, decimal_places=2)
    currency = models.CharField("Moneda", max_length=3, default="USD")
    max_users = models.PositiveIntegerField("Máx. usuarios (0 = ilimitado)", default=0)
    max_orders_month = models.PositiveIntegerField("Máx. órdenes/mes", default=0)
    max_storage_mb = models.PositiveIntegerField("Máx. almacenamiento (MB)", default=0)
    features = models.JSONField("Características", default=dict, blank=True)
    is_public = models.BooleanField("Visible en precios", default=True)

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Planes"

    def __str__(self) -> str:
        return self.name


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Prueba"
        ACTIVA = "ACTIVA", "Activa"
        VENCIDA = "VENCIDA", "Vencida"
        CANCELADA = "CANCELADA", "Cancelada"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    started_at = models.DateTimeField(auto_now_add=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Suscripción"
        verbose_name_plural = "Suscripciones"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.tenant} — {self.plan} ({self.status})"


class PlatformSettings(models.Model):
    """Configuración de la plataforma Ordo Lab (esquema `public`, una sola fila). La edita
    el administrador del SaaS en el admin de `public`; los laboratorios no la ven.

    Fase 11 (ADR-027): la firma de la plataforma al pie de cada informe PDF."""

    report_brand_enabled = models.BooleanField(
        "Mostrar la firma de Ordo Lab en los informes", default=True)
    report_brand_text = models.CharField(
        "Texto al pie del informe", max_length=160,
        default="Generado con Ordo Lab · Sistema de gestión para laboratorios clínicos")
    report_brand_contact = models.CharField(
        "Contacto de Ordo Lab (opcional)", max_length=160, blank=True, default="",
        help_text="Teléfono, Instagram o web; se imprime junto al texto.")

    class Meta:
        verbose_name = "Configuración de la plataforma"
        verbose_name_plural = "Configuración de la plataforma"

    def __str__(self) -> str:
        return "Configuración de la plataforma"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    @classmethod
    def get_solo(cls) -> "PlatformSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
