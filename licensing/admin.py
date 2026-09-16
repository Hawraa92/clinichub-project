from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import ngettext

from .models import Installation, LicenseAuditEvent, LicenseRecord


@admin.register(Installation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ("id", "display_name", "machine_fingerprint", "created_at")
    readonly_fields = (
        "id",
        "machine_fingerprint",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not Installation.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Revoke selected licenses")
def revoke_licenses(modeladmin, request, queryset):
    changed = queryset.filter(is_revoked=False).update(
        is_revoked=True,
        is_active=False,
    )
    modeladmin.message_user(
        request,
        ngettext(
            "%d license was revoked.",
            "%d licenses were revoked.",
            changed,
        )
        % changed,
        messages.WARNING,
    )


@admin.register(LicenseRecord)
class LicenseRecordAdmin(admin.ModelAdmin):
    list_display = (
        "license_id",
        "customer_name",
        "plan",
        "expires_at",
        "is_active",
        "is_revoked",
        "activated_at",
    )
    list_filter = ("plan", "is_active", "is_revoked")
    search_fields = ("license_id", "customer_name", "customer_email")
    actions = (revoke_licenses,)
    readonly_fields = (
        "license_id",
        "installation",
        "product",
        "customer_name",
        "customer_email",
        "plan",
        "issued_at",
        "not_before",
        "expires_at",
        "grace_days",
        "max_offline_days",
        "modules",
        "limits",
        "claims",
        "masked_token",
        "activated_at",
        "activated_by",
        "last_verified_at",
        "last_online_success_at",
        "next_online_check_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    exclude = ("license_token",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LicenseAuditEvent)
class LicenseAuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "license",
        "actor",
        "success",
        "ip_address",
        "created_at",
    )
    list_filter = ("event_type", "success", "created_at")
    search_fields = ("message", "license__license_id", "license__customer_name")
    readonly_fields = (
        "event_type",
        "license",
        "actor",
        "success",
        "message",
        "metadata",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
