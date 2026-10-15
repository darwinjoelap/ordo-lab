from django.urls import path

from apps.core import views, views_aux

app_name = "core"

urlpatterns = [
    path("estilo/", views.style_guide, name="style-guide"),
    path("tablas/", views_aux.hub, name="aux-hub"),
    path("tablas/<slug:key>/", views_aux.table_list, name="aux-list"),
    path("tablas/<slug:key>/nuevo/", views_aux.table_edit, name="aux-new"),
    path("tablas/<slug:key>/<uuid:pk>/", views_aux.table_edit, name="aux-edit"),
    # PWA base (Fase 13). Montado en la raíz por config/urls_tenant.py, así que estas
    # tres rutas quedan en "/sw.js", "/manifest.webmanifest" y "/offline/" tal cual el
    # service worker y el <link rel="manifest"> las esperan.
    path("sw.js", views.service_worker, name="service-worker"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("offline/", views.offline, name="offline"),
]
