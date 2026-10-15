from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# TODO(futuro): landing pública de Biolife en "" — hoy el panel de plataforma vive en
# /panel/ (Fase 12) para dejar la raíz libre para esa landing.

urlpatterns = [
    path("panel/", include("apps.tenants.urls")),
    path("cuenta/", include("apps.accounts.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
