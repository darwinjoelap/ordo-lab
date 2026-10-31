"""Consultas de órdenes y muestras."""
from __future__ import annotations

import datetime

from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from apps.orders.models import LabelPrint, Order, OrderItem, Sample


def _day_bounds(day: datetime.date):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return start, start + datetime.timedelta(days=1)


def order_list(*, day: datetime.date | None = None, status: str = "", query: str = "",
               pending_only: bool = False) -> QuerySet[Order]:
    """Órdenes del día, más recientes primero. Con búsqueda, o con `pending_only`
    (muestras por tomar, lista de trabajo de la toma), de cualquier día."""
    orders = Order.objects.select_related("patient").annotate(
        pending_samples=Count("samples", filter=Q(samples__status=Sample.Status.PENDIENTE),
                              distinct=True),
        item_count=Count("items", distinct=True),
    )
    query = query.strip()
    if query:
        digits = query.replace("-", "")
        orders = orders.filter(
            Q(number__icontains=query) | Q(samples__barcode=digits)
            | Q(patient__document_number__icontains=query)
            | Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__internal_code__icontains=query)
        ).distinct()
    elif pending_only:
        orders = orders.filter(samples__status=Sample.Status.PENDIENTE).exclude(
            status=Order.Status.ANULADA).distinct()
    elif day is not None:
        start, end = _day_bounds(day)
        orders = orders.filter(ordered_at__gte=start, ordered_at__lt=end)
    if status:
        orders = orders.filter(status=status)
    return orders.order_by("-ordered_at")


def order_detail(*, pk) -> Order:
    return (
        Order.objects.select_related("patient", "created_by", "paid_by", "cancelled_by",
                                     "delivered_by")
        .prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related(
                "test", "test__section", "profile").order_by("order_index")),
            Prefetch("samples", queryset=Sample.objects.select_related(
                "container_type", "collected_by", "rejected_by", "replaces")
                .prefetch_related(Prefetch("order_items", queryset=OrderItem.objects
                                           .select_related("test")))
                .order_by("sequence")),
        )
        .get(pk=pk)
    )


def samples_for_labels(*, order: Order, sample_ids=None) -> list[Sample]:
    """Muestras a imprimir: las indicadas, o todas las no rechazadas."""
    samples = Sample.objects.filter(order=order).select_related(
        "container_type", "order", "order__patient").prefetch_related(
        Prefetch("order_items", queryset=OrderItem.objects.select_related("test"))
    ).order_by("sequence")
    if sample_ids:
        return list(samples.filter(id__in=sample_ids))
    return list(samples.exclude(status=Sample.Status.RECHAZADA))


def sample_of_order(*, order: Order, pk) -> Sample:
    return order.samples.select_related("order", "container_type").get(pk=pk)


def find_order_by_code(*, code: str) -> Order | None:
    """Número de orden o de muestra, con o sin guiones (lo que teclea un lector)."""
    digits = code.strip().replace("-", "")
    if not digits:
        return None
    sample = Sample.objects.select_related("order").filter(barcode=digits).first()
    if sample:
        return sample.order
    if len(digits) == 10:
        return Order.objects.filter(number=f"{digits[:6]}-{digits[6:]}").first()
    return None


def day_summary(*, day: datetime.date) -> dict:
    start, end = _day_bounds(day)
    orders = Order.objects.filter(ordered_at__gte=start, ordered_at__lt=end).exclude(
        status=Order.Status.ANULADA
    )
    return {
        "orders": orders.count(),
        "pending_samples": Sample.objects.filter(
            order__in=orders, status=Sample.Status.PENDIENTE
        ).count(),
        "urgent": orders.filter(priority=Order.Priority.URGENTE).count(),
        "unpaid": orders.filter(is_paid=False).count(),
    }


def items_for_results(*, order: Order) -> list[OrderItem]:
    """Exámenes vigentes de la orden con sus tubos (captura de resultados, Fase 10)."""
    return list(
        order.items.exclude(status=OrderItem.Status.ANULADO)
        .select_related("test", "test__section", "profile")
        .prefetch_related("samples")
        .order_by("test__section__order_index", "order_index")
    )


def get_order(*, pk) -> Order:
    return Order.objects.select_related("patient").get(pk=pk)


WORKLIST_STATUSES = {
    "por_cargar": (OrderItem.Status.PENDIENTE, OrderItem.Status.EN_PROCESO),
    "por_validar": (OrderItem.Status.CARGADO,),
    "validados": (OrderItem.Status.VALIDADO,),
}


def results_worklist(*, status: str = "por_cargar", section_id: str = "",
                     query: str = "") -> QuerySet[OrderItem]:
    """Bandeja de resultados (Fase 10): exámenes por cargar, por validar o validados;
    urgentes y más antiguos primero. Excluye órdenes anuladas."""
    items = (
        OrderItem.objects.filter(status__in=WORKLIST_STATUSES.get(
            status, WORKLIST_STATUSES["por_cargar"]))
        .exclude(order__status=Order.Status.ANULADA)
        .select_related("order__patient", "test__section")
        .prefetch_related("samples")
    )
    if section_id:
        items = items.filter(test__section_id=section_id)
    query = query.strip()
    if query:
        items = items.filter(
            Q(order__number__icontains=query) | Q(order__patient__last_name__icontains=query)
            | Q(order__patient__first_name__icontains=query)
            | Q(order__patient__document_number__icontains=query)
        )
    if status == "validados":
        return items.order_by("-updated_at")[:200]
    return items.order_by("-order__priority", "order__ordered_at", "order_index")


def results_worklist_counts() -> dict:
    items = OrderItem.objects.exclude(order__status=Order.Status.ANULADA)
    return {key: items.filter(status__in=statuses).count()
            for key, statuses in WORKLIST_STATUSES.items() if key != "validados"}


# Informes (Fase 11) -------------------------------------------------------------------
REPORT_TABS = ("listas", "parciales", "entregadas")


def orders_for_reports(*, tab: str = "listas", query: str = "") -> QuerySet[Order]:
    """Bandeja de informes: *listas* (todo validado, sin entregar), *parciales* (algún
    examen validado y otros pendientes) y *entregadas* (las últimas 200)."""
    orders = Order.objects.select_related("patient").exclude(status=Order.Status.ANULADA)
    query = query.strip()
    if query:
        orders = orders.filter(
            Q(number__icontains=query) | Q(patient__document_number__icontains=query)
            | Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query))
    if tab == "entregadas":
        return orders.filter(status=Order.Status.ENTREGADA).order_by("-delivered_at")[:200]
    if tab == "parciales":
        return (orders.filter(items__status=OrderItem.Status.VALIDADO)
                .exclude(status__in=(Order.Status.VALIDADA, Order.Status.ENTREGADA))
                .distinct().order_by("ordered_at"))
    return orders.filter(status=Order.Status.VALIDADA).order_by("ordered_at")


def report_tab_counts() -> dict:
    return {tab: orders_for_reports(tab=tab).count() for tab in ("listas", "parciales")}


def report_order_facts(*, order: Order) -> dict:
    """Datos de la orden que el informe necesita y que no son resultados: exámenes aún
    sin validar (informe parcial) y **cuándo se tomaron las muestras**.

    Se devuelven la primera y la última, no sólo la primera. Con todas las muestras
    tomadas en el mostrador las dos coinciden y da igual; pero una orden puede mezclar un
    envase de orina recogido ayer en casa con una sangre extraída hoy (ADR-039), y
    entonces imprimir sólo la primera dice que la hematología se tomó treinta horas antes
    de lo que se tomó. Visto en producción el 2026-10-30.
    """
    pending = list(
        order.items.exclude(status__in=(OrderItem.Status.VALIDADO, OrderItem.Status.ANULADO))
        .order_by("test__section__order_index", "order_index")
        .values_list("test__name", flat=True))
    tomas = list(order.samples.filter(status=Sample.Status.TOMADA)
                 .exclude(collected_at=None)
                 .order_by("collected_at").values_list("collected_at", flat=True))
    return {
        "pending_tests": pending,
        "collected_at": tomas[0] if tomas else None,
        "collected_until": tomas[-1] if tomas else None,
    }


# Muestras por tomar (lista de trabajo de la toma) ----------------------------------------
def collection_worklist(*, query: str = "") -> list[Order]:
    """Órdenes con tubos por tomar para la pantalla del auxiliar. Cada orden trae:
    `pending` (tubos por tomar), `printed` (cuántos de ésos ya tienen etiqueta impresa),
    `pending_ids`, `last_print` (la impresión más reciente: quién y cuándo) y
    `all_printed`. Primero las que nadie ha atendido (urgentes y más antiguas arriba);
    las que ya tienen todas sus etiquetas impresas, al final."""
    orders = list(
        Order.objects.filter(samples__status=Sample.Status.PENDIENTE)
        .exclude(status=Order.Status.ANULADA).select_related("patient")
        .annotate(item_count=Count("items", distinct=True)).distinct()
    )
    query = query.strip()
    if query:
        needle = query.lower()
        orders = [o for o in orders if needle in " ".join((
            o.number, o.patient.first_name, o.patient.last_name,
            o.patient.document_number or "", o.patient.internal_code)).lower()]
    by_id = {o.pk: o for o in orders}
    for order in orders:
        order.pending_ids, order.printed, order.last_print = [], 0, None
    for sample in (Sample.objects.filter(order_id__in=by_id, status=Sample.Status.PENDIENTE)
                   .annotate(print_count=Count("prints")).order_by("sequence")):
        order = by_id[sample.order_id]
        order.pending_ids.append(sample.pk)
        order.printed += sample.print_count > 0
    for label in (LabelPrint.objects.filter(sample__order_id__in=by_id,
                                            sample__status=Sample.Status.PENDIENTE)
                  .select_related("created_by").order_by("-created_at")):
        order = by_id[label.sample.order_id]
        if order.last_print is None:
            order.last_print = label
    for order in orders:
        order.pending = len(order.pending_ids)
        order.all_printed = order.pending > 0 and order.printed == order.pending
    orders.sort(key=lambda o: (o.all_printed, o.priority != Order.Priority.URGENTE,
                               o.ordered_at))
    return orders


def patient_orders(*, patient, limit: int = 100) -> list[Order]:
    """Historial de órdenes del paciente (Fase 11e), la más reciente primero, con sus
    exámenes."""
    return list(
        Order.objects.filter(patient=patient)
        .prefetch_related(Prefetch("items", queryset=OrderItem.objects.select_related(
            "test").order_by("order_index")))
        .order_by("-ordered_at")[:limit]
    )
