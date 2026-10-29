"""Formularios de la recepción (Fase 09). Los querysets vienen de selectores de cada app."""
from django import forms
from django.utils import timezone

from apps.billing.selectors.price_queries import (
    active_currencies,
    default_price_list,
    usable_discounts,
    valid_price_lists,
)
from apps.catalog.selectors.catalog_queries import orderable_profiles, orderable_tests
from apps.orders.models import Order
from apps.patients.selectors.patient_search import active_patients


class OrderForm(forms.Form):
    patient = forms.ModelChoiceField(queryset=active_patients(), widget=forms.HiddenInput,
                                     error_messages={"required": "Elija un paciente."})
    tests = forms.ModelMultipleChoiceField(queryset=orderable_tests(), required=False,
                                           widget=forms.MultipleHiddenInput)
    profiles = forms.ModelMultipleChoiceField(queryset=orderable_profiles(), required=False,
                                              widget=forms.MultipleHiddenInput)
    priority = forms.ChoiceField(label="Prioridad", choices=Order.Priority.choices,
                                 initial=Order.Priority.NORMAL)
    requested_by = forms.CharField(label="Médico solicitante", max_length=150,
                                   required=False)
    price_list = forms.ModelChoiceField(label="Lista de precios", queryset=None,
                                        required=False, empty_label="— sin lista —")
    reference_currency = forms.ModelChoiceField(label="Mostrar también en", queryset=None,
                                                required=False, empty_label="—")
    discounts = forms.ModelMultipleChoiceField(label="Descuentos", queryset=None,
                                               required=False,
                                               widget=forms.CheckboxSelectMultiple)
    authorized = forms.BooleanField(label="Descuento autorizado", required=False)
    weight_kg = forms.DecimalField(label="Peso (kg)", required=False, max_digits=5,
                                   decimal_places=1, min_value=0)
    height_cm = forms.DecimalField(label="Talla (cm)", required=False, max_digits=5,
                                   decimal_places=1, min_value=0)
    urine_volume_24h_ml = forms.DecimalField(label="Orina 24 h (mL)", required=False,
                                             max_digits=7, decimal_places=1, min_value=0)
    notes = forms.CharField(label="Observaciones", required=False,
                            widget=forms.TextInput)

    def __init__(self, *args, require_patient: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["patient"].required = require_patient
        self.fields["price_list"].queryset = valid_price_lists(on_date=today)
        self.fields["price_list"].initial = default_price_list(on_date=today)
        self.fields["reference_currency"].queryset = active_currencies()
        self.fields["discounts"].queryset = usable_discounts(on_date=today)

    def clean(self):
        cleaned = super().clean()
        if not self.errors and not cleaned.get("tests") and not cleaned.get("profiles"):
            raise forms.ValidationError("Agregue al menos un examen o perfil.")
        return cleaned

    def order_kwargs(self) -> dict:
        data = self.cleaned_data
        return {
            "tests": list(data["tests"]), "profiles": list(data["profiles"]),
            "price_list": data.get("price_list"), "discounts": list(data["discounts"]),
            "reference_currency": data.get("reference_currency"),
            "authorized": data.get("authorized", False),
            "weight_kg": data.get("weight_kg"), "height_cm": data.get("height_cm"),
            "urine_volume_24h_ml": data.get("urine_volume_24h_ml"),
        }


class AddItemsForm(forms.Form):
    tests = forms.ModelMultipleChoiceField(queryset=orderable_tests(), required=False,
                                           widget=forms.MultipleHiddenInput)
    profiles = forms.ModelMultipleChoiceField(queryset=orderable_profiles(), required=False,
                                              widget=forms.MultipleHiddenInput)

    def clean(self):
        cleaned = super().clean()
        if not self.errors and not cleaned.get("tests") and not cleaned.get("profiles"):
            raise forms.ValidationError("Elija al menos un examen o perfil.")
        return cleaned


class ReasonForm(forms.Form):
    reason = forms.CharField(label="Motivo", max_length=255)


class ReceivedSampleForm(forms.Form):
    """Muestra que llega ya tomada.

    La hora es obligatoria y se pide de verdad, no se asume la de ahora: una glicemia de
    hace cinco horas no se lee igual que una recién tomada, y rellenarla por comodidad
    disimularía un dato que el laboratorio necesita para decidir si acepta la muestra.
    """

    origin = forms.ChoiceField(label="Procedencia", choices=[])
    origin_detail = forms.CharField(
        label="¿De dónde?", max_length=150, required=False,
        help_text="Clínica, laboratorio o persona que la trajo.",
    )
    collected_at = forms.DateTimeField(
        label="Tomada el", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        error_messages={"required": "Indique la hora en que se tomó la muestra."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sin `LABORATORIO`: esa procedencia se registra con la toma normal.
        from apps.orders.models import Sample
        self.fields["origin"].choices = [
            (value, label) for value, label in Sample.Origin.choices
            if value != Sample.Origin.LABORATORIO
        ]

    def clean_collected_at(self):
        collected_at = self.cleaned_data["collected_at"]
        if collected_at > timezone.now():
            raise forms.ValidationError("La hora de toma no puede estar en el futuro.")
        return collected_at
