from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path("", core_views.home, name="tenant-home"),
    path("", include("apps.core.urls")),
    path("cuenta/", include("apps.accounts.urls")),
    path("ordenes/", include("apps.orders.urls")),
    path("pacientes/", include("apps.patients.urls")),
    path("resultados/", include("apps.results.urls")),
    path("informes/", include("apps.reports.urls")),
    path("configuracion/laboratorio/", include("apps.settings_lab.urls")),
    path("configuracion/", include("apps.accounts.urls_lab")),
    path("catalogo/", include("apps.catalog.urls")),
    path("precios/", include("apps.billing.urls")),
    path("verificar/", include("apps.reports.urls_public")),
    path("sincronizacion/", include("apps.sync.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar
    from django.conf.urls.static import static

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
