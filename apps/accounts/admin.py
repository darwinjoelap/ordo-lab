from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import Membership, Role, User


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1


@admin.register(User)
class OrdoLabUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Datos de Ordo Lab", {"fields": ("phone", "professional_title", "professional_license",
                                         "signature_image", "stamp_image")}),
    )
    inlines = [MembershipInline]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_system")
    list_filter = ("is_system",)
