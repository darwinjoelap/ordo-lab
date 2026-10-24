from django.db import models


class Locality(models.Model):
    name = models.CharField("Nombre", max_length=120)
    state = models.CharField("Estado", max_length=80)
    municipality = models.CharField("Municipio", max_length=120, blank=True, default="")

    class Meta:
        verbose_name = "Localidad"
        verbose_name_plural = "Localidades"
        unique_together = [("name", "state")]
        ordering = ["state", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.state})"


class OfficialRate(models.Model):
    """Tasa oficial del día, **global** (vive en el esquema `public`).

    La trae el cron desde el BCV una vez al día y la ven todos los laboratorios, igual
    que en Ordo. Cada laboratorio puede sobrescribirla con su propia `billing.ExchangeRate`
    —por ejemplo el día que el BCV no responda— y esa manda si es de fecha igual o
    posterior (`billing.services.exchange.get_exchange_rate`).

    Las monedas se guardan como **código ISO, no como FK**: `billing.Currency` es un
    modelo de tenant y desde `public` no se puede apuntar a él.
    """

    class Source(models.TextChoices):
        BCV = "BCV", "BCV automático"
        MANUAL = "MANUAL", "Carga manual"

    from_code = models.CharField("De (ISO 4217)", max_length=3, default="USD")
    to_code = models.CharField("A (ISO 4217)", max_length=3, default="VES")
    rate = models.DecimalField("Tasa", max_digits=20, decimal_places=8)
    effective_date = models.DateField("Vigente desde")
    source = models.CharField("Fuente", max_length=10, choices=Source.choices,
                              default=Source.BCV)
    notes = models.CharField("Notas", max_length=255, blank=True, default="")
    fetched_at = models.DateTimeField("Actualizada en", auto_now=True)

    class Meta:
        verbose_name = "Tasa oficial"
        verbose_name_plural = "Tasas oficiales"
        ordering = ["-effective_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_code", "to_code", "effective_date"],
                name="officialrate_unique_pair_date",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gt=0), name="officialrate_rate_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.effective_date:%d/%m/%Y}: 1 {self.from_code} = {self.rate} {self.to_code}"
