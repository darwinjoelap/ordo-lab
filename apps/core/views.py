"""Pantallas base del laboratorio (Fase 08d) y PWA base (Fase 13). Sólo orquestan: no
tocan el ORM."""
from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Inicio del laboratorio. Los indicadores reales llegan con órdenes (Fase 09)."""
    return render(request, "core/home.html")


class DemoPatientForm(forms.Form):
    """Formulario de ejemplo para la guía de estilo (no guarda nada)."""

    document_type = forms.ChoiceField(
        label="Tipo", choices=[("V", "V"), ("E", "E"), ("P", "P"), ("SIN", "Sin doc.")]
    )
    document_number = forms.CharField(label="Cédula", required=False, max_length=12)
    first_name = forms.CharField(label="Nombres")
    last_name = forms.CharField(label="Apellidos")
    sex = forms.ChoiceField(label="Sexo", choices=[("F", "Femenino"), ("M", "Masculino")])
    birth_date = forms.DateField(
        label="Fecha de nacimiento", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Si no se conoce, indique la edad declarada.",
    )
    phone = forms.CharField(label="Teléfono", required=False)
    email = forms.EmailField(label="Correo", required=False)
    locality = forms.ChoiceField(
        label="Localidad", required=False,
        choices=[("", "—"), ("SJM", "San Juan de los Morros"), ("VC", "Villa de Cura")],
    )
    address = forms.CharField(label="Dirección", required=False)
    requested_by = forms.CharField(label="Médico solicitante", required=False)
    priority = forms.ChoiceField(label="Prioridad", choices=[("N", "Normal"), ("U", "Urgente")])


@staff_member_required
def style_guide(request):
    """Guía de estilo viva: tokens y componentes con datos de ejemplo."""
    form = DemoPatientForm(request.GET or None)
    if request.GET:
        form.is_valid()
    return render(request, "core/style_guide.html", {"form": form})


# --- PWA base (Fase 13) ------------------------------------------------------------
# Sin @login_required: el navegador pide estos tres sin pasar por una sesión "normal"
# (instalación del service worker, lectura del manifest); exigir sesión aquí cachearía
# una redirección al login en vez del script o la página de respaldo.

def service_worker(request):
    """Se sirve en la raíz ("/sw.js", registrado así en apps.core.urls incluido sin
    prefijo) para que su alcance por defecto sea todo el origen del laboratorio."""
    return render(request, "core/sw.js", content_type="application/javascript")


def manifest(request):
    return render(
        request, "core/manifest.webmanifest", content_type="application/manifest+json"
    )


def offline(request):
    """Respaldo del service worker cuando la página pedida no estaba en caché."""
    return render(request, "core/offline.html")
