from django.urls import path

from apps.results import views

app_name = "results"

urlpatterns = [
    path("", views.worklist, name="worklist"),
    path("orden/<uuid:pk>/", views.capture, name="capture"),
    path("orden/<uuid:pk>/calcular/", views.live, name="live"),
    path("orden/<uuid:pk>/validar/", views.validate, name="validate"),
    path("orden/<uuid:pk>/datos/", views.clinical_data, name="clinical-data"),
    path("orden/<uuid:pk>/valores/<uuid:value_pk>/aviso/", views.critical_notice,
         name="critical-notice"),
    path("orden/<uuid:pk>/examenes/<uuid:result_pk>/rectificar/", views.amend,
         name="amend"),
]
