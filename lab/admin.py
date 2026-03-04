# lab/admin.py
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import LabOrder, LabResult, LabSettings


# =========================
# Inlines
# =========================
class LabResultInline(admin.StackedInline):
    model = LabResult
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("status", "result_text", "attachment", "verified_by", "verified_at", "updated_at")
    readonly_fields = ("verified_by", "verified_at", "updated_at")


# =========================
# LabSettings (Singleton)
# =========================
@admin.register(LabSettings)
class LabSettingsAdmin(admin.ModelAdmin):
    list_display = ("lab_name", "max_upload_mb", "allow_pdf", "allow_images", "require_verify_before_ready", "updated_at")
    fields = (
        "lab_name",
        "lab_phone",
        "lab_address",
        "lab_logo",
        "max_upload_mb",
        "allow_pdf",
        "allow_images",
        "require_verify_before_ready",
        "default_result_template",
        "footer_note",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        # Singleton: لا نسمح بإضافة أكثر من سجل
        return not LabSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # الأفضل ما نحذف الإعدادات حتى لا تتكسر المنظومة
        return False


# =========================
# LabOrder Admin
# =========================
@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "doctor",
        "appointment",
        "status",
        "urgency",
        "created_at",
        "doctor_seen_at",
        "has_doctor_attachment",
        "has_result",
        "result_verified",
    )
    list_filter = ("status", "urgency", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    search_fields = (
        "id",
        "patient__full_name",
        "doctor__user__username",
        "doctor__user__email",
        "requested_tests_text",
        "notes",
    )

    list_select_related = ("patient", "doctor", "doctor__user", "appointment")
    autocomplete_fields = ("patient", "doctor", "appointment")

    inlines = [LabResultInline]

    actions = ("mark_in_progress", "mark_ready", "mark_cancelled")

    @admin.display(boolean=True, description="Doctor PDF")
    def has_doctor_attachment(self, obj: LabOrder) -> bool:
        return bool(getattr(obj, "doctor_attachment", None))

    @admin.display(boolean=True, description="Has Result")
    def has_result(self, obj: LabOrder) -> bool:
        try:
            _ = obj.result  # related_name="result"
            return True
        except Exception:
            return False

    @admin.display(boolean=True, description="Verified")
    def result_verified(self, obj: LabOrder) -> bool:
        try:
            res = obj.result
            return getattr(res, "status", None) == LabResult.Status.VERIFIED
        except Exception:
            return False

    @admin.action(description="Mark selected orders as IN_PROGRESS")
    def mark_in_progress(self, request, queryset):
        updated = queryset.exclude(status=LabOrder.Status.CANCELLED).update(status=LabOrder.Status.IN_PROGRESS)
        self.message_user(request, f"✅ Updated: {updated} order(s) → IN_PROGRESS", level=messages.SUCCESS)

    @admin.action(description="Mark selected orders as READY (enforce verification policy)")
    def mark_ready(self, request, queryset):
        ok = 0
        failed = 0
        for o in queryset:
            try:
                o.mark_ready(reset_doctor_seen=True)
                ok += 1
            except ValidationError as e:
                failed += 1
                self.message_user(
                    request,
                    f"❌ Order #{o.pk}: cannot mark READY ({'; '.join(e.messages)})",
                    level=messages.ERROR,
                )
            except Exception:
                failed += 1
                self.message_user(
                    request,
                    f"❌ Order #{o.pk}: cannot mark READY (unexpected error)",
                    level=messages.ERROR,
                )

        if ok:
            self.message_user(request, f"✅ READY: {ok} order(s)", level=messages.SUCCESS)
        if failed and not ok:
            self.message_user(request, f"⚠️ Failed: {failed} order(s)", level=messages.WARNING)

    @admin.action(description="Mark selected orders as CANCELLED")
    def mark_cancelled(self, request, queryset):
        updated = queryset.update(status=LabOrder.Status.CANCELLED)
        self.message_user(request, f"🛑 Cancelled: {updated} order(s)", level=messages.SUCCESS)


# =========================
# LabResult Admin
# =========================
@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "verified_by", "verified_at", "updated_at")
    list_filter = ("status", "verified_at", "updated_at")
    date_hierarchy = "updated_at"
    ordering = ("-updated_at", "-id")

    search_fields = (
        "id",
        "order__id",
        "order__patient__full_name",
        "order__doctor__user__username",
        "result_text",
    )

    list_select_related = ("order", "order__patient", "order__doctor", "order__doctor__user", "verified_by")
    autocomplete_fields = ("order", "verified_by")
    readonly_fields = ("verified_at", "updated_at")