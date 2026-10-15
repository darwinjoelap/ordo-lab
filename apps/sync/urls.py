from django.urls import path

from apps.sync import views

app_name = "sync"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("mutaciones/", views.mutations, name="mutations"),
    path("bloque/", views.number_block, name="number-block"),
    path("bloque/consumido/", views.block_consumed, name="block-consumed"),
    path("estado/", views.status, name="status"),
    path("<uuid:pk>/reintentar/", views.retry, name="retry"),
    path("conflictos/<uuid:pk>/revisado/", views.resolve, name="resolve"),
]
