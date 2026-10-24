from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

# TODO(futuro): landing pública de Ordo Lab en "" — hoy el panel de plataforma vive en
# /panel/ (Fase 12) para dejar la raíz libre para esa landing. Mientras tanto la raíz
# redirige al panel: antes era un 404, y es a donde `LOGIN_REDIRECT_URL` lleva al entrar
# por el dominio de plataforma.

urlpatterns = [
    path("", RedirectView.as_view(url="/panel/", permanent=False), name="platform-home"),
    path("panel/", include("apps.tenants.urls")),
    path("cuenta/", include("apps.accounts.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
