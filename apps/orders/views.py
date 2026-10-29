"""Pantallas de recepción (Fase 09): lista, nueva orden, detalle, tubos y etiquetas.
Las vistas sólo orquestan: validan con formularios y llaman a services/selectors."""
import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import (
    COLLECTION_ROLES,
    RECEPTION_ROLES,
    VIEW_ORDER_ROLES,
    VIEW_ROLES,
    role_required,
    ui_permissions,
    user_has_any_role,
)
from apps.catalog.selectors.catalog_queries import search_orderables
from apps.core.exceptions import ApplicationError
from apps.orders.forms import AddItemsForm, OrderForm, ReasonForm, ReceivedSampleForm
from apps.orders.models import Order, Sample
from apps.orders.selectors import order_queries as q
from apps.orders.services.labels import print_labels
from apps.orders.services.order_creation import build_draft, create_order
from apps.orders.services.order_management import (
    add_to_order,
    cancel_order,
    mark_paid,
    requote_pending,
)
from apps.orders.services.sample_collection import (
    collect_all,
    collect_sample,
    receive_sample,
    reject_sample,
)
from apps.patients.selectors.patient_queries import active_antecedents
from apps.patients.selectors.patient_search import get_patient, search_patients
from apps.patients.services.patient_age import patient_age_text
from apps.settings_lab.models import TenantSettings


def _get_order(pk) -> Order:
    try:
        return q.order_detail(pk=pk)
    except (Order.DoesNotExist, ValueError, ValidationError) as exc:
        raise Http404("Orden no encontrada.") from exc


def _parse_day(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return timezone.localdate()


def _collection_context(request, query: str) -> dict:
    return {"orders": q.collection_worklist(query=query), "query": query,
            "pending_only": True, "can_print": user_has_any_role(request.user,
                                                                  *COLLECTION_ROLES)}


@role_required(*VIEW_ORDER_ROLES)
def collection_table(request):
    """Tabla de *Muestras por tomar* (htmx): se refresca sola cada 20 s."""
    return render(request, "orders/_collection_table.html",
                  _collection_context(request, request.GET.get("q", "").strip()))


@role_required(*VIEW_ORDER_ROLES)
def order_list(request):
    query = request.GET.get("q", "").strip()
    found = q.find_order_by_code(code=query) if query else None
    if found:  # lector de código de barras: directo a la orden
        return redirect("orders:detail", pk=found.pk)
    # El auxiliar de toma sólo trabaja con «Muestras por tomar».
    if request.GET.get("pendientes") == "1" or ui_permissions(request.user)[
            "only_collection"]:
        return render(request, "orders/collection.html", _collection_context(request, query))
    day = _parse_day(request.GET.get("dia"))
    orders = q.order_list(day=day, status=request.GET.get("estado", ""), query=query,
                          pending_only=request.GET.get("pendientes") == "1")
    return render(request, "orders/order_list.html", {
        "orders": orders, "day": day, "query": query, "statuses": Order.Status.choices,
        "status": request.GET.get("estado", ""), "summary": q.day_summary(day=day),
        "pending_only": request.GET.get("pendientes") == "1",
        "prev_day": day - datetime.timedelta(days=1),
        "next_day": day + datetime.timedelta(days=1),
    })


@role_required(*RECEPTION_ROLES)
def order_new(request):
    form = OrderForm(request.POST or None,
                     initial={"patient": request.GET.get("paciente")})
    if request.method == "POST" and form.is_valid():
        try:
            order, warnings = create_order(
                patient=form.cleaned_data["patient"], priority=form.cleaned_data["priority"],
                requested_by=form.cleaned_data["requested_by"],
                notes=form.cleaned_data["notes"], created_by=request.user,
                **form.order_kwargs())
        except ApplicationError as exc:
            form.add_error(None, exc.message)
        else:
            _flash(request, f"Orden {order.number} registrada.", warnings)
            return redirect("orders:detail", pk=order.pk)
    patient = get_patient(pk=form["patient"].value()) if form["patient"].value() else None
    return render(request, "orders/order_new.html", {
        "form": form, "patient": patient,
        "patient_age": patient_age_text(patient) if patient else "",
        "selected": _selected_items(form),
    })


def _flash(request, text, warnings) -> None:
    messages.success(request, text)
    for warning in warnings:
        messages.warning(request, warning)


def _selected_items(form) -> list[dict]:
    """Ítems ya elegidos (para repintar los chips si el POST vuelve con errores)."""
    if not form.is_bound or not hasattr(form, "cleaned_data"):
        return []
    items = [{"id": str(p.pk), "code": p.code, "name": p.name, "kind": "profiles"}
             for p in form.cleaned_data.get("profiles", [])]
    return items + [{"id": str(t.pk), "code": t.code, "name": t.name, "kind": "tests"}
                    for t in form.cleaned_data.get("tests", [])]


@role_required(*RECEPTION_ROLES)
@require_POST
def order_preview(request):
    """Resumen en vivo (htmx): cotización, avisos y tubos, sin guardar."""
    form = OrderForm(request.POST, require_patient=False)
    draft, error = None, ""
    if form.is_valid():
        try:
            draft = build_draft(**form.order_kwargs())
        except ApplicationError as exc:
            error = exc.message
    return render(request, "orders/_summary.html",
                  {"draft": draft, "error": error, "form": form})


@role_required(*RECEPTION_ROLES)
def orderables_search(request):
    profiles, tests = search_orderables(query=request.GET.get("oq", ""))
    return render(request, "orders/_orderables.html", {"profiles": profiles, "tests": tests})


@role_required(*RECEPTION_ROLES)
def patients_search(request):
    patients = search_patients(query=request.GET.get("pq", ""))[:10]
    return render(request, "orders/_patients.html", {"patients": patients})


@role_required(*VIEW_ORDER_ROLES)
def order_detail(request, pk):
    order = _get_order(pk)
    # Vigentes en orden de extracción; las rechazadas al final, como historial.
    samples = sorted(order.samples.all(), key=lambda s: (
        s.status == Sample.Status.RECHAZADA, s.container_type.draw_order, s.sequence))
    return render(request, "orders/order_detail.html", {
        "order": order, "samples": samples,
        "active_samples": [s for s in samples if s.status != Sample.Status.RECHAZADA],
        "pending": sum(s.status == Sample.Status.PENDIENTE for s in samples),
        "patient_age": patient_age_text(order.patient, as_of=order.ordered_at.date()),
        "antecedents": active_antecedents(patient=order.patient),
        "editable": order.status in (Order.Status.REGISTRADA, Order.Status.MUESTRA_TOMADA),
        # Marcar tomada se permite aunque ya haya resultados cargados (se cargó antes de
        # registrar la toma); no en una orden anulada o entregada.
        "can_collect": order.status not in (Order.Status.ANULADA, Order.Status.ENTREGADA),
        # Sin `LABORATORIO`: esa procedencia se registra con el botón de toma normal.
        "origin_choices": [(v, label) for v, label in Sample.Origin.choices
                           if v != Sample.Origin.LABORATORIO],
    })


@role_required(*COLLECTION_ROLES)
def labels_pdf(request, pk):
    order = _get_order(pk)
    try:
        samples = q.samples_for_labels(order=order,
                                       sample_ids=request.GET.getlist("muestra"))
    except ValidationError:
        samples = []
    if not samples:
        raise Http404("La orden no tiene muestras para imprimir.")
    settings_obj = TenantSettings.get_solo()
    pdf = print_labels(
        order=order, samples=samples, user=request.user,
        width_mm=settings_obj.label_width_mm, height_mm=settings_obj.label_height_mm,
        include_order_label=(settings_obj.label_extra_for_order
                             and not request.GET.getlist("muestra")),
    )
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="etiquetas-{order.number}.pdf"'
    return response


def _run(request, pk, action, success: str):
    """Ejecuta una acción de servicio sobre la orden y vuelve al detalle."""
    order = _get_order(pk)
    try:
        result = action(order)
    except (ApplicationError, Sample.DoesNotExist, ValidationError) as exc:
        messages.error(request, getattr(exc, "message", "Muestra no encontrada."))
    else:
        messages.success(request, success.format(result=result))
    return redirect("orders:detail", pk=pk)


@role_required(*COLLECTION_ROLES)
@require_POST
def sample_collect(request, pk):
    sample_id = request.POST.get("muestra")
    if sample_id:
        return _run(request, pk, lambda o: collect_sample(
            sample=q.sample_of_order(order=o, pk=sample_id), user=request.user).number,
            "Muestra {result} tomada.")
    return _run(request, pk, lambda o: collect_all(order=o, user=request.user),
                "{result} muestra(s) marcadas como tomadas.")


@role_required(*COLLECTION_ROLES)
@require_POST
def sample_receive(request, pk, sample_pk):
    """Muestra que llegó ya tomada: procedencia y hora declarada.

    No lleva `data-offline`: recibir una muestra externa no está en el vocabulario de
    mutaciones de la cola (Fase 14), así que esto exige conexión. Es aceptable porque
    ocurre en el mostrador, no en la sala de toma, pero conviene saberlo.
    """
    form = ReceivedSampleForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(
            m for errores in form.errors.values() for m in errores))
        return redirect("orders:detail", pk=pk)
    return _run(request, pk, lambda o: receive_sample(
        sample=q.sample_of_order(order=o, pk=sample_pk),
        origin=form.cleaned_data["origin"],
        origin_detail=form.cleaned_data["origin_detail"],
        collected_at=form.cleaned_data["collected_at"],
        user=request.user).number,
        "Muestra {result} registrada como recibida ya tomada.")


@role_required(*COLLECTION_ROLES)
@require_POST
def sample_reject(request, pk, sample_pk):
    form = ReasonForm(request.POST)
    reason = form.data.get("reason", "")
    return _run(request, pk, lambda o: reject_sample(
        sample=q.sample_of_order(order=o, pk=sample_pk), reason=reason,
        user=request.user).number,
        "Muestra rechazada. Reemplazo {result}: imprima su etiqueta.")


@role_required(*RECEPTION_ROLES)
@require_POST
def order_pay(request, pk):
    return _run(request, pk, lambda o: mark_paid(order=o, user=request.user).number,
                "Orden {result} marcada como pagada.")


@role_required(*RECEPTION_ROLES)
@require_POST
def order_requote(request, pk):
    def requote(order):
        requote_pending(order=order)
        return order.number
    return _run(request, pk, requote, "Orden {result} recotizada con los precios actuales.")


@role_required(*RECEPTION_ROLES)
@require_POST
def order_cancel(request, pk):
    reason = request.POST.get("reason", "")
    return _run(request, pk, lambda o: cancel_order(order=o, reason=reason,
                                                    user=request.user).number,
                "Orden {result} anulada.")


@role_required(*RECEPTION_ROLES)
def order_add(request, pk):
    order = _get_order(pk)
    form = AddItemsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            warnings = add_to_order(order=order, tests=list(form.cleaned_data["tests"]),
                                    profiles=list(form.cleaned_data["profiles"]),
                                    user=request.user)
        except ApplicationError as exc:
            form.add_error(None, exc.message)
        else:
            _flash(request, "Exámenes agregados. Revise los tubos nuevos.", warnings)
            return redirect("orders:detail", pk=order.pk)
    return render(request, "orders/order_add.html", {"order": order, "form": form})


@role_required(*VIEW_ROLES)
def day_summary_partial(request):
    """Indicadores del día para la pantalla de Inicio (htmx)."""
    return render(request, "orders/_day_kpis.html",
                  {"summary": q.day_summary(day=timezone.localdate()),
                   "results": q.results_worklist_counts()})
