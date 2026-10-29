from django.urls import path

from apps.orders import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("nueva/", views.order_new, name="new"),
    path("resumen-del-dia/", views.day_summary_partial, name="day-summary"),
    path("por-tomar/tabla/", views.collection_table, name="collection-table"),
    path("nueva/resumen/", views.order_preview, name="preview"),
    path("buscar/examenes/", views.orderables_search, name="search-orderables"),
    path("buscar/pacientes/", views.patients_search, name="search-patients"),
    path("<uuid:pk>/", views.order_detail, name="detail"),
    path("<uuid:pk>/etiquetas.pdf", views.labels_pdf, name="labels"),
    path("<uuid:pk>/tomar/", views.sample_collect, name="collect"),
    path("<uuid:pk>/muestras/<uuid:sample_pk>/recibir/", views.sample_receive,
         name="receive"),
    path("<uuid:pk>/muestras/<uuid:sample_pk>/rechazar/", views.sample_reject,
         name="reject"),
    path("<uuid:pk>/pagar/", views.order_pay, name="pay"),
    path("<uuid:pk>/recotizar/", views.order_requote, name="requote"),
    path("<uuid:pk>/anular/", views.order_cancel, name="cancel"),
    path("<uuid:pk>/agregar/", views.order_add, name="add"),
]
