"""Panel de plataforma (Fase 12): laboratorios, planes y suscripciones, sin /admin.
Sólo entra quien pase `platform_required` (sesión + `is_superuser` en `public`)."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.tenants.decorators import platform_required
from apps.tenants.forms import PlanForm, SubscriptionForm, TenantCreateForm, TenantEditForm
from apps.tenants.models import Plan, Subscription, Tenant
from apps.tenants.services.metrics import platform_metrics
from apps.tenants.services.provisioning import provision_tenant
from apps.tenants.services.suspension import reactivate_tenant, suspend_tenant


def _layout(form):
    """(campo, columnas, es_casilla) — misma idea que apps.core.views_aux._layout,
    pero este panel no usa el motor de tablas auxiliares (TENANT_APP, no corre en
    `public`), así que no se reutiliza directamente."""
    return [
        (bound, "col-6", getattr(bound.field.widget, "input_type", "") == "checkbox")
        for bound in form.visible_fields()
    ]


def _labs():
    return Tenant.objects.exclude(schema_name="public")


@platform_required
def dashboard(request):
    return render(request, "tenants/dashboard.html", {"metrics": platform_metrics()})


@platform_required
def tenant_list(request):
    status = request.GET.get("estado", "")
    query = request.GET.get("q", "")
    qs = _labs().order_by("name")
    if status:
        qs = qs.filter(status=status)
    if query:
        qs = qs.filter(
            Q(name__icontains=query) | Q(schema_name__icontains=query)
            | Q(rif__icontains=query)
        )
    return render(request, "tenants/tenant_list.html", {
        "tenants": qs, "status": status, "query": query,
        "status_choices": Tenant.Status.choices,
    })


@platform_required
def tenant_new(request):
    form = TenantCreateForm(request.POST or None, initial={"trial_days": 30})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            tenant, admin_password = provision_tenant(
                name=data["name"], schema_name=data["schema_name"],
                subdomain=data["subdomain"], admin_email=data["admin_email"],
                plan=data["plan"], rif=data["rif"] or None,
                trial_days=data["trial_days"], seed_catalog=not data["sin_catalogo"],
            )
        except ApplicationError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(
                request,
                f"Laboratorio «{tenant.name}» creado. Admin: {data['admin_email']} — "
                f"contraseña temporal: {admin_password}. Cópiela ahora: no queda "
                "registrada en ningún lado.",
            )
            return redirect("tenants:tenant-detail", pk=tenant.pk)
    return render(request, "tenants/tenant_new.html", {"form": form, "fields": _layout(form)})


@platform_required
def tenant_detail(request, pk):
    tenant = get_object_or_404(_labs(), pk=pk)
    edit_form = TenantEditForm(instance=tenant)
    if request.method == "POST" and request.POST.get("accion") == "editar":
        edit_form = TenantEditForm(request.POST, instance=tenant)
        if edit_form.is_valid():
            edit_form.save()
            messages.success(request, "Datos del laboratorio actualizados.")
            return redirect("tenants:tenant-detail", pk=tenant.pk)
    subscription_form = SubscriptionForm(initial={
        "current_period_start": timezone.now(),
        "current_period_end": timezone.now() + timedelta(days=30),
    })
    return render(request, "tenants/tenant_detail.html", {
        "tenant": tenant,
        "edit_form": edit_form, "edit_fields": _layout(edit_form),
        "subscription_form": subscription_form,
        "subscription_fields": _layout(subscription_form),
        "subscriptions": tenant.subscriptions.select_related("plan").order_by("-started_at"),
        "domains": tenant.domains.all(),
    })


@platform_required
def tenant_suspend(request, pk):
    tenant = get_object_or_404(_labs(), pk=pk)
    if request.method == "POST":
        reason = request.POST.get("motivo", "").strip()
        suspend_tenant(
            tenant=tenant, by=request.user.get_full_name() or request.user.username,
            reason=reason,
        )
        messages.success(
            request, f"«{tenant.name}» quedó suspendido: no podrá entrar hasta reactivarlo.")
    return redirect("tenants:tenant-detail", pk=pk)


@platform_required
def tenant_reactivate(request, pk):
    tenant = get_object_or_404(_labs(), pk=pk)
    if request.method == "POST":
        reactivate_tenant(
            tenant=tenant, by=request.user.get_full_name() or request.user.username)
        messages.success(request, f"«{tenant.name}» quedó activo de nuevo.")
    return redirect("tenants:tenant-detail", pk=pk)


@platform_required
def subscription_new(request, pk):
    tenant = get_object_or_404(_labs(), pk=pk)
    if request.method == "POST":
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.tenant = tenant
            sub.save()
            messages.success(request, "Suscripción registrada.")
        else:
            messages.error(request, "Revise los datos de la suscripción.")
    return redirect("tenants:tenant-detail", pk=pk)


@platform_required
def subscription_cancel(request, pk):
    sub = get_object_or_404(Subscription, pk=pk)
    if request.method == "POST":
        sub.status = Subscription.Status.CANCELADA
        sub.save(update_fields=["status"])
        messages.success(request, "Suscripción cancelada.")
    return redirect("tenants:tenant-detail", pk=sub.tenant_id)


@platform_required
def plan_list(request):
    return render(request, "tenants/plan_list.html", {
        "plans": Plan.objects.all().order_by("price_monthly"),
    })


@platform_required
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Plan «{saved.name}» guardado.")
        return redirect("tenants:plan-edit", pk=saved.pk)
    return render(request, "tenants/plan_edit.html", {
        "form": form, "plan": plan, "fields": _layout(form),
    })
