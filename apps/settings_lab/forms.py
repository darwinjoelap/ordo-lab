import re

from django import forms

from apps.core.widgets import ImageInput
from apps.settings_lab.models import TenantSettings

SECTIONS = [
    ("Contacto (se imprime en el informe)", ["phone", "email", "address", "instagram",
                                             "website"]),
    ("Identidad visual", ["logo", "color_primary", "lab_initials"]),
    ("Informe", ["report_footer_text", "report_disclaimer", "report_link_days",
                 "report_external_sample_notice", "report_partial_notice"]),
    ("Operación", ["require_second_validation"]),
    ("Etiquetas de tubo", ["label_width_mm", "label_height_mm", "label_extra_for_order"]),
]


class LabSettingsForm(forms.ModelForm):
    website = forms.URLField(label="Sitio web", required=False, assume_scheme="https")

    class Meta:
        model = TenantSettings
        fields = [f for _, names in SECTIONS for f in names]
        widgets = {
            "color_primary": forms.TextInput(attrs={"type": "color"}),
            "report_footer_text": forms.Textarea(attrs={"rows": 2}),
            "report_disclaimer": forms.Textarea(attrs={"rows": 2}),
            "logo": ImageInput(),
        }
        help_texts = {
            "lab_initials": "Prefijo de la historia de los pacientes nuevos (p. ej. LDU). "
                            "Cambiarlo no afecta a los ya registrados.",
            "report_footer_text": "Opcional. Texto propio al pie de cada página del informe.",
            "report_disclaimer": "Opcional. Nota al final del informe.",
            "instagram": "Sin @; se imprime bajo el número de orden.",
            "require_second_validation": "Quien valida un resultado debe ser distinto de "
                                         "quien lo cargó.",
        }

    def clean_instagram(self):
        return self.cleaned_data["instagram"].strip().lstrip("@")

    def clean_lab_initials(self):
        value = self.cleaned_data["lab_initials"].strip().upper()
        if value and not re.fullmatch(r"[A-Z]{2,6}", value):
            raise forms.ValidationError("Use de 2 a 6 letras, sin espacios.")
        return value

    def clean_report_link_days(self):
        value = self.cleaned_data["report_link_days"]
        if not 1 <= value <= 365:
            raise forms.ValidationError("Entre 1 y 365 días.")
        return value

    def clean_label_width_mm(self):
        return self._label_size("label_width_mm", 25, 110)

    def clean_label_height_mm(self):
        return self._label_size("label_height_mm", 15, 80)

    def _label_size(self, name, low, high):
        value = self.cleaned_data[name]
        if not low <= value <= high:
            raise forms.ValidationError(f"Entre {low} y {high} mm.")
        return value

    def sections(self):
        return [(title, [self[name] for name in names]) for title, names in SECTIONS]
