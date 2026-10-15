from django.urls import path

from apps.tenants import views

app_name = "tenants"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("laboratorios/", views.tenant_list, name="tenant-list"),
    path("laboratorios/nuevo/", views.tenant_new, name="tenant-new"),
    path("laboratorios/<int:pk>/", views.tenant_detail, name="tenant-detail"),
    path("laboratorios/<int:pk>/suspender/", views.tenant_suspend, name="tenant-suspend"),
    path(
        "laboratorios/<int:pk>/reactivar/", views.tenant_reactivate, name="tenant-reactivate"
    ),
    path(
        "laboratorios/<int:pk>/suscripciones/nueva/", views.subscription_new,
        name="subscription-new",
    ),
    path(
        "suscripciones/<int:pk>/cancelar/", views.subscription_cancel,
        name="subscription-cancel",
    ),
    path("planes/", views.plan_list, name="plan-list"),
    path("planes/nuevo/", views.plan_edit, name="plan-new"),
    path("planes/<int:pk>/", views.plan_edit, name="plan-edit"),
]
