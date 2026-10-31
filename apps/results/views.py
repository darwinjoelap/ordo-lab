"""Pantallas de resultados (Fase 10): bandeja de trabajo y captura/validación por orden.
Las vistas sólo orquestan: formularios + services/selectors."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import (
    CAPTURE_ROLES,
    VIEW_ROLES,
    can_validate_results,
    role_required,
)
from apps.catalog.selectors.catalog_queries import active_sections
from apps.core.exceptions import ApplicationError
from apps.orders.models import Order
from apps.orders.selectors.order_queries import (
    get_order,
    results_worklist,
    results_worklist_counts,
)
from apps.orders.services.order_progress import update_clinical_data
from apps.patients.selectors.patient_queries import active_antecedents
from apps.patients.services.patient_age import patient_age_text
from apps.results.forms import (
    ClinicalDataForm,
    CriticalNoticeForm,
    entries_from_post,
    notes_from_post,
)
from apps.results.models import Result, ResultValue
from apps.results.selectors.result_queries import result_of_order, result_value_of_order
from apps.results.services.amendment import amend_result
from apps.results.services.result_capture import build_sheet, save_sheet
from apps.results.services.validation import notify_critical, validate_results


def _order(pk) -> Order:
    try:
        return get_order(pk=pk)
    except (Order.DoesNotExist, ValidationError) as exc:
        raise Http404("Orden no encontrada.") from exc


@role_required(*VIEW_ROLES)
def worklist(request):
    status = request.GET.get("estado", "por_cargar")
    items = results_worklist(status=status, section_id=request.GET.get("seccion", ""),
                             query=request.GET.get("q", ""))
    return render(request, "results/worklist.html", {
        "items": items, "status": status, "counts": results_worklist_counts(),
        "sections": active_sections(),
        "section_id": request.GET.get("seccion", ""), "query": request.GET.get("q", ""),
    })


def _render_capture(request, order, sheet, status=200):
    return render(request, "results/capture.html", {
        "order": order, "sheet": sheet, "patient_age": patient_age_text(
            order.patient, as_of=order.ordered_at.date()),
        "antecedents": active_antecedents(patient=order.patient),
        "can_validate": can_validate_results(request.user),
        "clinical_form": ClinicalDataForm(initial={
            "weight_kg": order.weight_kg, "height_cm": order.height_cm,
            "urine_volume_24h_ml": order.urine_volume_24h_ml,
            "patient_condition": order.patient_condition}),
        "notice_form": CriticalNoticeForm(),
    }, status=status)


@role_required(*VIEW_ROLES)
def capture(request, pk):
    order = _order(pk)
    if request.method == "POST":
        return _save(request, order)
    return _render_capture(request, order, build_sheet(order))


@role_required(*CAPTURE_ROLES)
def _save(request, order):
    entries, notes = entries_from_post(request.POST), notes_from_post(request.POST)
    try:
        sheet = save_sheet(order, entries=entries, notes=notes, user=request.user)
    except ApplicationError as exc:
        messages.error(request, exc.message)
        return _render_capture(request, order,
                               build_sheet(order, entries=entries, notes=notes), 400)
    messages.success(request, "Resultados guardados.")
    for warning in sheet.warnings:
        messages.warning(request, warning)
    return redirect("results:capture", pk=order.pk)


@role_required(*CAPTURE_ROLES)
@require_POST
def live(request, pk):
    """Cálculo en vivo (htmx): marcas, referencias y calculados, sin guardar."""
    order = _order(pk)
    sheet = build_sheet(order, entries=entries_from_post(request.POST))
    return render(request, "results/_live.html", {"sheet": sheet})


@role_required(*CAPTURE_ROLES)
@require_POST
def validate(request, pk):
    if not can_validate_results(request.user):
        raise PermissionDenied("Su rol no puede validar resultados.")
    order = _order(pk)
    sheet = None
    try:
        sheet = save_sheet(order, entries=entries_from_post(request.POST),
                           notes=notes_from_post(request.POST), user=request.user)
        validated = validate_results(order=order, result_ids=request.POST.getlist("result"),
                                     user=request.user)
    except ApplicationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"{len(validated)} examen(es) validado(s).")
    # Los avisos del guardado —suma de la fórmula leucocitaria, tubo sin marcar, lote
    # vencido— se muestran también aquí: validar es la última ocasión de atenderlos.
    for warning in (sheet.warnings if sheet else []):
        messages.warning(request, warning)
    return redirect("results:capture", pk=order.pk)


@role_required(*CAPTURE_ROLES)
@require_POST
def critical_notice(request, pk, value_pk):
    order = _order(pk)
    form = CriticalNoticeForm(request.POST)
    try:
        value = result_value_of_order(order=order, pk=value_pk)
        if not form.is_valid():
            raise ApplicationError("Complete el aviso: valor confirmado y a quién se avisó.")
        notify_critical(value=value, user=request.user, **form.cleaned_data)
    except (ApplicationError, ResultValue.DoesNotExist, ValidationError) as exc:
        messages.error(request, getattr(exc, "message", "Valor no encontrado."))
    else:
        messages.success(request, "Aviso del valor crítico registrado.")
    return redirect("results:capture", pk=order.pk)


@role_required(*CAPTURE_ROLES)
@require_POST
def clinical_data(request, pk):
    order = _order(pk)
    form = ClinicalDataForm(request.POST)
    if form.is_valid():
        try:
            update_clinical_data(order=order, **form.cleaned_data)
            save_sheet(order, entries={}, user=None)  # recalcula con los datos nuevos
        except ApplicationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "Datos del paciente actualizados; cálculos al día.")
    else:
        messages.error(request, "Revise peso, talla y volumen de orina.")
    return redirect("results:capture", pk=order.pk)


@role_required(*CAPTURE_ROLES)
@require_POST
def amend(request, pk, result_pk):
    """Abre una rectificación de un examen ya validado (Fase 15) y lo reabre para
    corregirlo. No cambia ningún valor: eso se hace en la captura de siempre."""
    if not can_validate_results(request.user):
        raise PermissionDenied("Su rol no puede rectificar resultados validados.")
    order = _order(pk)
    try:
        result = result_of_order(order=order, pk=result_pk)
        amend_result(result=result, reason=request.POST.get("reason", ""),
                     user=request.user)
    except (ApplicationError, Result.DoesNotExist, ValidationError) as exc:
        messages.error(request, getattr(exc, "message", "Examen no encontrado."))
    else:
        messages.warning(request, f"{result.order_item.test.name} quedó abierto para "
                         "corregir. Al validarlo de nuevo, emita el informe: saldrá como "
                         "rectificado.")
    return redirect("results:capture", pk=order.pk)
