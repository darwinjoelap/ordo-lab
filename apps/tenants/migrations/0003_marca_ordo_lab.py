"""Renombrado de la marca: Biolife → Ordo Lab (ADR-036).

Los textos del pie del informe no viven sólo en el código: `PlatformSettings` es una
fila real en el esquema `public`, creada antes del renombrado. Cambiar el `default` del
modelo no toca esa fila, así que los informes seguirían diciendo "Generado con Biolife".

Esta migración hace las dos cosas: ajusta los campos y corrige la fila existente **sólo
si conserva el texto por defecto anterior**. Si el administrador ya lo personalizó, no se
toca: su texto es suyo.
"""
from django.db import migrations, models

TEXTO_VIEJO = "Generado con Biolife · Sistema de gestión para laboratorios clínicos"
TEXTO_NUEVO = "Generado con Ordo Lab · Sistema de gestión para laboratorios clínicos"


def renombrar(apps, schema_editor):
    PlatformSettings = apps.get_model("tenants", "PlatformSettings")
    PlatformSettings.objects.filter(report_brand_text=TEXTO_VIEJO).update(
        report_brand_text=TEXTO_NUEVO
    )


def revertir(apps, schema_editor):
    PlatformSettings = apps.get_model("tenants", "PlatformSettings")
    PlatformSettings.objects.filter(report_brand_text=TEXTO_NUEVO).update(
        report_brand_text=TEXTO_VIEJO
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0002_configuracion_plataforma"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platformsettings",
            name="report_brand_enabled",
            field=models.BooleanField(
                default=True,
                verbose_name="Mostrar la firma de Ordo Lab en los informes",
            ),
        ),
        migrations.AlterField(
            model_name="platformsettings",
            name="report_brand_text",
            field=models.CharField(
                default=TEXTO_NUEVO,
                max_length=160,
                verbose_name="Texto al pie del informe",
            ),
        ),
        migrations.AlterField(
            model_name="platformsettings",
            name="report_brand_contact",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Teléfono, Instagram o web; se imprime junto al texto.",
                max_length=160,
                verbose_name="Contacto de Ordo Lab (opcional)",
            ),
        ),
        migrations.RunPython(renombrar, revertir),
    ]
