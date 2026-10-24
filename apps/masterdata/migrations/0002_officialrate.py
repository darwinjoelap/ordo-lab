from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masterdata", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OfficialRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("from_code", models.CharField(default="USD", max_length=3,
                                               verbose_name="De (ISO 4217)")),
                ("to_code", models.CharField(default="VES", max_length=3,
                                             verbose_name="A (ISO 4217)")),
                ("rate", models.DecimalField(decimal_places=8, max_digits=20,
                                             verbose_name="Tasa")),
                ("effective_date", models.DateField(verbose_name="Vigente desde")),
                ("source", models.CharField(
                    choices=[("BCV", "BCV automático"), ("MANUAL", "Carga manual")],
                    default="BCV", max_length=10, verbose_name="Fuente")),
                ("notes", models.CharField(blank=True, default="", max_length=255,
                                           verbose_name="Notas")),
                ("fetched_at", models.DateTimeField(auto_now=True,
                                                    verbose_name="Actualizada en")),
            ],
            options={
                "verbose_name": "Tasa oficial",
                "verbose_name_plural": "Tasas oficiales",
                "ordering": ["-effective_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="officialrate",
            constraint=models.UniqueConstraint(
                fields=("from_code", "to_code", "effective_date"),
                name="officialrate_unique_pair_date",
            ),
        ),
        migrations.AddConstraint(
            model_name="officialrate",
            constraint=models.CheckConstraint(
                condition=models.Q(rate__gt=0), name="officialrate_rate_positive"
            ),
        ),
    ]
