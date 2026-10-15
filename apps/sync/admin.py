"""Admin de consulta (Fase 14): diagnóstico de la cola, sin lógica de negocio. La
operación real vive en la pantalla de *Sincronización* (tramo C)."""
from django.contrib import admin

from apps.sync.models import Device, OrderNumberBlock, SyncConflict, SyncQueueEntry


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("label", "device_id", "last_user", "last_seen_at", "is_active")
    search_fields = ("label", "device_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrderNumberBlock)
class OrderNumberBlockAdmin(admin.ModelAdmin):
    list_display = ("device", "day", "from_value", "to_value", "consumed")
    list_filter = ("day",)
    search_fields = ("device__label", "device__device_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SyncQueueEntry)
class SyncQueueEntryAdmin(admin.ModelAdmin):
    list_display = ("kind", "target_label", "device", "status", "client_created_at",
                    "applied_at")
    list_filter = ("status", "kind")
    search_fields = ("target_label", "client_mutation_id", "device__label")
    readonly_fields = ("client_mutation_id", "payload", "created_at", "updated_at")


@admin.register(SyncConflict)
class SyncConflictAdmin(admin.ModelAdmin):
    list_display = ("entity", "field", "reason", "resolution", "created_at")
    list_filter = ("resolution", "reason")
    search_fields = ("entity", "field", "object_id")
    readonly_fields = ("queue_entry", "client_value", "server_value", "created_at",
                       "updated_at")
