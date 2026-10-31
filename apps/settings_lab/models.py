from django.db import models


class TenantSettings(models.Model):
    """
    Configuración del laboratorio. Singleton por esquema de tenant: no lleva FK a
    Tenant porque ya vive aislada dentro del esquema (ADR-001). `save()` fuerza
    `pk=1` y `delete()` no hace nada — siempre debe existir exactamente una fila.
    """

    class TimeFormat(models.TextChoices):
        H12 = "H12", "12 horas"
        H24 = "H24", "24 horas"

    class DecimalSeparator(models.TextChoices):
        COMA = "COMA", "Coma"
        PUNTO = "PUNTO", "Punto"

    # Identificación de pacientes (Fase 04)
    lab_initials = models.CharField(
        "Siglas del laboratorio", max_length=6, blank=True, default=""
    )

    # Identidad visual
    logo = models.ImageField("Logo", upload_to="branding/", blank=True, null=True)
    banner = models.ImageField("Banner", upload_to="branding/", blank=True, null=True)
    color_primary = models.CharField("Color primario", max_length=7, default="#1B5FA8")
    color_secondary = models.CharField(
        "Color secundario", max_length=7, blank=True, default=""
    )
    report_header_html = models.TextField("Cabecera del informe", blank=True, default="")
    report_footer_text = models.TextField("Pie del informe", blank=True, default="")
    report_disclaimer = models.TextField(
        "Descargo de responsabilidad", blank=True, default=""
    )

    # Contacto (impreso en el informe)
    phone = models.CharField("Teléfono", max_length=30, blank=True, default="")
    address = models.CharField("Dirección", max_length=255, blank=True, default="")
    email = models.EmailField("Correo", blank=True, default="")
    instagram = models.CharField("Instagram", max_length=100, blank=True, default="")
    website = models.URLField("Sitio web", blank=True, default="")

    # Localización
    timezone = models.CharField("Zona horaria", max_length=50, default="America/Caracas")
    time_format = models.CharField(
        "Formato de hora", max_length=3, choices=TimeFormat.choices, default=TimeFormat.H12
    )
    date_format = models.CharField("Formato de fecha", max_length=20, default="dd/MM/yyyy")
    decimal_separator = models.CharField(
        "Separador decimal",
        max_length=5,
        choices=DecimalSeparator.choices,
        default=DecimalSeparator.COMA,
    )

    # Operación
    # El número de orden es diario, AAMMDD-NNNN, y lo lleva apps.orders (ADR-024).
    require_second_validation = models.BooleanField(
        "Requiere doble validación", default=False
    )

    # Etiquetas de tubo (Fase 09, ADR-024): PDF del tamaño exacto de la etiqueta térmica.
    label_width_mm = models.PositiveSmallIntegerField(
        "Ancho de etiqueta (mm)", default=50
    )
    label_height_mm = models.PositiveSmallIntegerField(
        "Alto de etiqueta (mm)", default=25
    )
    # Informe (Fase 11, ADR-027)
    report_link_days = models.PositiveSmallIntegerField(
        "Días que el PDF se puede descargar desde el QR", default=30,
        help_text="Pasado este plazo, la página de verificación sigue confirmando el "
                  "informe pero ya no permite descargarlo.",
    )
    report_external_sample_notice = models.BooleanField(
        "Advertir en el informe las muestras que no se tomaron aquí", default=True,
        help_text="Imprime un aviso con la procedencia y la hora declarada cuando una "
                  "muestra llegó ya tomada. Afecta sólo a los informes que se emitan "
                  "desde ahora: los ya emitidos conservan lo que decían.",
    )
    label_extra_for_order = models.BooleanField(
        "Etiqueta extra para la hoja de la orden", default=False,
        help_text="Imprime una etiqueta más, con el número de orden, para pegar en la "
                  "solicitud.",
    )

    class Meta:
        verbose_name = "Configuración del laboratorio"
        verbose_name_plural = "Configuración del laboratorio"

    def __str__(self) -> str:
        return "Configuración del laboratorio"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls) -> "TenantSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
