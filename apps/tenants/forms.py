"""Formularios del panel de plataforma (Fase 12)."""
from __future__ import annotations

import re

from django import forms

from apps.tenants.models import Plan, Subscription, Tenant

_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Nombre del laboratorio", max_length=200)
    schema_name = forms.CharField(
        label="Esquema", max_length=63,
        help_text="Minúsculas, números o guion bajo, empieza con letra. Ej.: lab_angelus.",
    )
    subdomain = forms.CharField(
        label="Subdominio", max_length=63,
        help_text="Ej.: angelus — queda como angelus.<dominio base>.",
    )
    admin_email = forms.EmailField(label="Correo del administrador inicial")
    rif = forms.CharField(label="RIF", max_length=20, required=False)
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.none(), required=False, label="Plan (opcional)")
    trial_days = forms.IntegerField(label="Días de prueba", min_value=0, initial=30)
    sin_catalogo = forms.BooleanField(
        label="Nace vacío (sin catálogo, perfiles ni monedas sembrados)", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(is_public=True)

    def clean_schema_name(self):
        value = self.cleaned_data["schema_name"].strip().lower()
        if not _SCHEMA_RE.match(value):
            raise forms.ValidationError(
                "Use minúsculas, números o guion bajo, empezando por una letra "
                "(3 a 31 caracteres)."
            )
        return value

    def clean_subdomain(self):
        return self.cleaned_data["subdomain"].strip().lower()


class TenantEditForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["name", "legal_name", "rif", "paid_until", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "paid_until": forms.DateInput(attrs={"type": "date"}),
        }


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            "code", "name", "price_monthly", "currency", "max_users",
            "max_orders_month", "max_storage_mb", "is_public",
        ]


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = [
            "plan", "status", "current_period_start", "current_period_end",
            "cancel_at_period_end",
        ]
        widgets = {
            "current_period_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "current_period_end": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
