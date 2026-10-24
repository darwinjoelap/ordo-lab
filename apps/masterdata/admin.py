from django.contrib import admin

from apps.masterdata.models import Locality, OfficialRate


@admin.register(Locality)
class LocalityAdmin(admin.ModelAdmin):
    list_display = ("name", "state", "municipality")
    list_filter = ("state",)
    search_fields = ("name", "municipality")


@admin.register(OfficialRate)
class OfficialRateAdmin(admin.ModelAdmin):
    """La tasa oficial es global: se administra desde `public`, no desde un laboratorio."""

    list_display = ("effective_date", "from_code", "to_code", "rate", "source",
                    "fetched_at")
    list_filter = ("source", "from_code", "to_code")
    date_hierarchy = "effective_date"
