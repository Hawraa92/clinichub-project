# appointments/admin.py
from __future__ import annotations

from datetime import date as py_date

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Model
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Appointment, Notification, PatientBookingRequest

# These enums exist in your codebase, but we keep safe fallbacks anyway.
try:
    from .models import AppointmentStatus  # type: ignore
except Exception:  # pragma: no cover
    AppointmentStatus = None  # type: ignore

try:
    from .models import BookingRequestStatus  # type: ignore
except Exception:  # pragma: no cover
    BookingRequestStatus = None  # type: ignore


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _model_has_field(model: type[Model], field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _safe_status_value(obj, field_name: str = "status") -> str:
    try:
        return str(getattr(obj, field_name))
    except Exception:
        return ""


def _status_label(obj, field_name: str = "status") -> str:
    try:
        fn = getattr(obj, "get_status_display", None)
        if callable(fn):
            return str(fn())
    except Exception:
        pass
    return _safe_status_value(obj, field_name) or "—"


def _is_soft_deleted(obj) -> bool:
    if hasattr(obj, "is_deleted"):
        try:
            return bool(getattr(obj, "is_deleted"))
        except Exception:
            return False
    if hasattr(obj, "deleted_at"):
        try:
            return bool(getattr(obj, "deleted_at"))
        except Exception:
            return False
    return False


# -------------------------------------------------------------------
# Soft Delete Admin Mixin (Appointments)
# -------------------------------------------------------------------
class SoftDeleteAdminMixin:
    """
    - يجعل حذف الأدمن Soft Delete بدل Hard Delete
    - يضيف Restore/Hard Delete كـ Actions
    - يعرض حتى المحذوفات (all_objects) إذا موجودة
    """

    def get_queryset(self, request):
        # ✅ Show deleted rows too in admin list
        if hasattr(self.model, "all_objects"):
            return self.model.all_objects.all()
        return super().get_queryset(request)

    def delete_model(self, request, obj):
        # ✅ Delete from admin = Soft Delete
        try:
            obj.delete(user=request.user)  # if SoftDeleteModel supports deleted_by
            return
        except TypeError:
            pass
        except Exception:
            pass

        # fallback: if model delete() already soft-deletes
        try:
            obj.delete()
            return
        except Exception:
            # final fallback: default behavior
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        # ✅ Bulk delete = Soft Delete (avoid queryset.delete hard deletion)
        for obj in queryset:
            self.delete_model(request, obj)

    @admin.action(description="♻️ Restore selected (undo soft delete)")
    def restore_selected(self, request, queryset):
        restored = 0
        for obj in queryset:
            try:
                if hasattr(obj, "restore"):
                    obj.restore()
                    restored += 1
                    continue
            except Exception:
                pass

            # fallback manual restore
            try:
                updated = False
                if hasattr(obj, "is_deleted"):
                    obj.is_deleted = False
                    updated = True
                if hasattr(obj, "deleted_at"):
                    obj.deleted_at = None
                    updated = True
                if hasattr(obj, "deleted_by"):
                    obj.deleted_by = None
                    updated = True
                if updated:
                    obj.save()
                    restored += 1
            except Exception:
                continue

        self.message_user(request, f"✅ Restored: {restored}", level=messages.SUCCESS)

    @admin.action(description="🧨 Hard delete selected (SUPERUSER ONLY)")
    def hard_delete_selected(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied("Hard delete is restricted to superusers only.")

        model = queryset.model
        ids = list(queryset.values_list("pk", flat=True))

        # QuerySet.delete() = physical delete (does not call model.delete())
        if hasattr(model, "all_objects"):
            model.all_objects.filter(pk__in=ids).delete()
        else:
            model.objects.filter(pk__in=ids).delete()

        self.message_user(request, f"⚠️ Hard deleted: {len(ids)}", level=messages.WARNING)

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Hide hard delete from non-superusers
        if not request.user.is_superuser and "hard_delete_selected" in actions:
            del actions["hard_delete_selected"]
        return actions


# ---------------------------
# Custom Filters
# ---------------------------
class AppointmentDateRangeFilter(admin.SimpleListFilter):
    title = _("Time Range")
    parameter_name = "time_range"

    def lookups(self, request, model_admin):
        return [
            ("past", _("Past")),
            ("today", _("Today")),
            ("future", _("Future")),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset

        if not _model_has_field(Appointment, "scheduled_time"):
            return queryset

        today = timezone.localdate()
        if value == "past":
            return queryset.filter(scheduled_time__date__lt=today)
        if value == "today":
            return queryset.filter(scheduled_time__date=today)
        if value == "future":
            return queryset.filter(scheduled_time__date__gt=today)
        return queryset


# ---------------------------
# Appointment Admin
# ---------------------------
@admin.register(Appointment)
class AppointmentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_per_page = 50

    # ✅ IMPORTANT:
    # Required because LabOrderAdmin.autocomplete_fields references Appointment via LabOrder.appointment
    # Django system check (admin.E040) requires AppointmentAdmin.search_fields to be set.
    search_fields = (
        "patient__full_name",
        "patient__mobile",
        "patient__email",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "doctor__user__username",
        "doctor__user__email",
    )

    # ✅ add restore/hard-delete actions in addition to yours
    actions = ["mark_completed", "mark_cancelled", "restore_selected", "hard_delete_selected"]

    autocomplete_fields = tuple(f for f in ("patient", "doctor") if _model_has_field(Appointment, f))

    def get_list_select_related(self, request):
        sr = []
        if _model_has_field(Appointment, "patient"):
            sr.append("patient")
        if _model_has_field(Appointment, "doctor"):
            sr.append("doctor")
            sr.append("doctor__user")  # common in your project
        return tuple(dict.fromkeys(sr))

    def get_date_hierarchy(self, request):
        return "scheduled_time" if _model_has_field(Appointment, "scheduled_time") else None

    def get_ordering(self, request):
        if _model_has_field(Appointment, "scheduled_time"):
            return ("-scheduled_time",)
        return ("-pk",)

    def get_readonly_fields(self, request, obj=None):
        rf = []
        for f in ("queue_number", "created_at"):
            if _model_has_field(Appointment, f):
                rf.append(f)
        return tuple(rf)

    def get_list_filter(self, request):
        lf = []
        if _model_has_field(Appointment, "doctor"):
            lf.append("doctor")
        if _model_has_field(Appointment, "status"):
            lf.append("status")
        lf.append(AppointmentDateRangeFilter)
        if _model_has_field(Appointment, "is_deleted"):
            lf.append("is_deleted")
        return lf

    def get_search_fields(self, request):
        """
        Keep the class-level `search_fields` (required by admin checks),
        but allow adding optional fields if they exist.
        """
        sf = list(self.search_fields or ())
        if _model_has_field(Appointment, "notes") and "notes" not in sf:
            sf.append("notes")
        return tuple(sf)

    def get_list_editable(self, request):
        # Only allow inline editing if status exists AND is not readonly
        if _model_has_field(Appointment, "status") and "status" not in self.get_readonly_fields(request):
            return ("status",)
        return ()

    def get_list_display(self, request):
        cols = [
            "get_patient_name",
            "get_patient_age",
            "get_doctor_name",
        ]
        if _model_has_field(Appointment, "scheduled_time"):
            cols.append("scheduled_time")
        if _model_has_field(Appointment, "queue_number"):
            cols.append("queue_number")
        if _model_has_field(Appointment, "iqd_amount"):
            cols.append("amount_iqd")
        if _model_has_field(Appointment, "status"):
            cols.extend(["status", "colored_status"])
        else:
            cols.append("colored_status")

        # Optional soft-delete visibility + restore button
        if _model_has_field(Appointment, "is_deleted"):
            cols.append("is_deleted")
            cols.append("restore_button")

        return cols

    # ✅ Restore button in list view (only for deleted rows)
    @admin.display(description="Restore")
    def restore_button(self, obj: Appointment):
        if not _model_has_field(Appointment, "is_deleted"):
            return "-"
        if not _is_soft_deleted(obj):
            return "-"
        url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_restore", args=[obj.pk])
        return format_html('<a class="button" href="{}">Restore</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/restore/",
                self.admin_site.admin_view(self.restore_one),
                name=f"{self.model._meta.app_label}_{self.model._meta.model_name}_restore",
            )
        ]
        return custom + urls

    def restore_one(self, request, pk: int):
        obj = get_object_or_404(self.get_queryset(request), pk=pk)

        try:
            if hasattr(obj, "restore"):
                obj.restore()
            else:
                updated = False
                if hasattr(obj, "is_deleted"):
                    obj.is_deleted = False
                    updated = True
                if hasattr(obj, "deleted_at"):
                    obj.deleted_at = None
                    updated = True
                if hasattr(obj, "deleted_by"):
                    obj.deleted_by = None
                    updated = True
                if updated:
                    obj.save()
        except Exception:
            self.message_user(request, "❌ Restore failed.", level=messages.ERROR)
            return redirect(request.META.get("HTTP_REFERER") or "../")

        self.message_user(request, "✅ Restored successfully.", level=messages.SUCCESS)
        return redirect(request.META.get("HTTP_REFERER") or "../")

    # ----- Display helpers -----
    @admin.display(description=_("Patient Name"), ordering="patient__full_name")
    def get_patient_name(self, obj: Appointment):
        p = getattr(obj, "patient", None)
        return getattr(p, "full_name", None) or "—"

    @admin.display(description=_("Patient Age"))
    def get_patient_age(self, obj: Appointment):
        p = getattr(obj, "patient", None)
        if not p:
            return "—"

        age = getattr(p, "age", None)
        if age is not None:
            return age

        dob = getattr(p, "date_of_birth", None)
        if dob:
            today = py_date.today()
            years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return years
        return "—"

    @admin.display(description=_("Doctor"), ordering="doctor__user__first_name")
    def get_doctor_name(self, obj: Appointment):
        doc = getattr(obj, "doctor", None)
        if not doc:
            return "—"

        display = getattr(doc, "get_display_name", None)
        if callable(display):
            v = (display() or "").strip()
            if v:
                return v

        u = getattr(doc, "user", None)
        if u:
            return u.get_full_name() or getattr(u, "first_name", "") or getattr(u, "username", "") or "—"

        return str(doc) or "—"

    @admin.display(description=_("Amount (IQD)"), ordering="iqd_amount")
    def amount_iqd(self, obj: Appointment):
        if not _model_has_field(Appointment, "iqd_amount"):
            return "—"
        val = getattr(obj, "iqd_amount", None)
        try:
            return f"{int(val):,}"
        except Exception:
            return val if val is not None else "—"

    @admin.display(description=_("Status"))
    def colored_status(self, obj: Appointment):
        status_val = _safe_status_value(obj, "status")

        pending = getattr(AppointmentStatus, "PENDING", "pending") if AppointmentStatus else "pending"
        completed = getattr(AppointmentStatus, "COMPLETED", "completed") if AppointmentStatus else "completed"
        cancelled = getattr(AppointmentStatus, "CANCELLED", "cancelled") if AppointmentStatus else "cancelled"
        confirmed = getattr(AppointmentStatus, "CONFIRMED", "confirmed") if AppointmentStatus else "confirmed"
        called = getattr(AppointmentStatus, "CALLED", "called") if AppointmentStatus else "called"

        color_map = {
            str(pending): "#ffc107",
            str(confirmed): "#0d6efd",
            str(called): "#6f42c1",
            str(completed): "#28a745",
            str(cancelled): "#dc3545",
        }

        label = _status_label(obj, "status")
        color = color_map.get(status_val, "#6c757d")
        return format_html(
            '<span style="padding:2px 6px; border-radius:4px; '
            'background:{}; color:#fff; font-size:12px;">{}</span>',
            color,
            label,
        )

    # ----- Actions -----
    @admin.action(description=_("Mark selected appointments as COMPLETED"))
    def mark_completed(self, request, queryset):
        if not _model_has_field(Appointment, "status"):
            self.message_user(request, _("Status field not found."), level=messages.ERROR)
            return
        completed = getattr(AppointmentStatus, "COMPLETED", "completed") if AppointmentStatus else "completed"
        updated = queryset.update(status=completed)
        self.message_user(request, _("%(n)s appointment(s) marked as completed.") % {"n": updated})

    @admin.action(description=_("Mark selected appointments as CANCELLED"))
    def mark_cancelled(self, request, queryset):
        if not _model_has_field(Appointment, "status"):
            self.message_user(request, _("Status field not found."), level=messages.ERROR)
            return
        cancelled = getattr(AppointmentStatus, "CANCELLED", "cancelled") if AppointmentStatus else "cancelled"
        updated = queryset.update(status=cancelled)
        self.message_user(request, _("%(n)s appointment(s) marked as cancelled.") % {"n": updated})


# ---------------------------
# Patient Booking Request Admin
# ---------------------------
@admin.register(PatientBookingRequest)
class PatientBookingRequestAdmin(admin.ModelAdmin):
    list_per_page = 50
    actions = ["mark_as_confirmed", "mark_as_rejected"]

    autocomplete_fields = tuple(f for f in ("doctor",) if _model_has_field(PatientBookingRequest, f))

    def get_list_select_related(self, request):
        sr = []
        if _model_has_field(PatientBookingRequest, "doctor"):
            sr.append("doctor")
            sr.append("doctor__user")
        return tuple(dict.fromkeys(sr))

    def get_date_hierarchy(self, request):
        return "submitted_at" if _model_has_field(PatientBookingRequest, "submitted_at") else None

    def get_ordering(self, request):
        if _model_has_field(PatientBookingRequest, "submitted_at"):
            return ("-submitted_at",)
        return ("-pk",)

    def get_readonly_fields(self, request, obj=None):
        return ("submitted_at",) if _model_has_field(PatientBookingRequest, "submitted_at") else ()

    def get_list_filter(self, request):
        lf = []
        if _model_has_field(PatientBookingRequest, "status"):
            lf.append("status")
        if _model_has_field(PatientBookingRequest, "doctor"):
            lf.append("doctor")
        return lf

    def get_search_fields(self, request):
        sf = []
        if _model_has_field(PatientBookingRequest, "full_name"):
            sf.append("full_name")
        if _model_has_field(PatientBookingRequest, "contact_info"):
            sf.append("contact_info")
        if _model_has_field(PatientBookingRequest, "doctor"):
            sf.extend(["doctor__user__first_name", "doctor__user__last_name"])
        return sf

    def get_list_editable(self, request):
        if _model_has_field(PatientBookingRequest, "status") and "status" not in self.get_readonly_fields(request):
            return ("status",)
        return ()

    def get_list_display(self, request):
        cols = []
        if _model_has_field(PatientBookingRequest, "full_name"):
            cols.append("full_name")
        if _model_has_field(PatientBookingRequest, "doctor"):
            cols.append("doctor")
        if _model_has_field(PatientBookingRequest, "scheduled_time"):
            cols.append("scheduled_time")
        if _model_has_field(PatientBookingRequest, "status"):
            cols.extend(["status", "colored_status"])
        else:
            cols.append("colored_status")
        if _model_has_field(PatientBookingRequest, "submitted_at"):
            cols.append("submitted_at")
        return cols

    @admin.display(description=_("Status"))
    def colored_status(self, obj: PatientBookingRequest):
        status_val = _safe_status_value(obj, "status")

        pending = getattr(BookingRequestStatus, "PENDING", "pending") if BookingRequestStatus else "pending"
        requested = getattr(BookingRequestStatus, "REQUESTED", "requested") if BookingRequestStatus else "requested"
        confirmed = getattr(BookingRequestStatus, "CONFIRMED", "confirmed") if BookingRequestStatus else "confirmed"
        rejected = getattr(BookingRequestStatus, "REJECTED", "rejected") if BookingRequestStatus else "rejected"

        color_map = {
            str(pending): "#ffc107",
            str(requested): "#ffc107",
            str(confirmed): "#28a745",
            str(rejected): "#dc3545",
        }

        label = _status_label(obj, "status")
        color = color_map.get(status_val, "#6c757d")
        return format_html(
            '<span style="padding:2px 6px; border-radius:4px; '
            'background:{}; color:#fff; font-size:12px;">{}</span>',
            color,
            label,
        )

    @admin.action(description=_("Mark selected booking requests as CONFIRMED"))
    def mark_as_confirmed(self, request, queryset):
        if not _model_has_field(PatientBookingRequest, "status"):
            self.message_user(request, _("Status field not found."), level=messages.ERROR)
            return
        confirmed = getattr(BookingRequestStatus, "CONFIRMED", "confirmed") if BookingRequestStatus else "confirmed"
        updated = queryset.update(status=confirmed)
        self.message_user(request, _("%(n)s booking request(s) marked as confirmed.") % {"n": updated})

    @admin.action(description=_("Mark selected booking requests as REJECTED"))
    def mark_as_rejected(self, request, queryset):
        if not _model_has_field(PatientBookingRequest, "status"):
            self.message_user(request, _("Status field not found."), level=messages.ERROR)
            return
        rejected = getattr(BookingRequestStatus, "REJECTED", "rejected") if BookingRequestStatus else "rejected"
        updated = queryset.update(status=rejected)
        self.message_user(request, _("%(n)s booking request(s) marked as rejected.") % {"n": updated})


# ---------------------------
# Notification Admin
# ---------------------------
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_per_page = 50
    list_filter = ["is_read"] if _model_has_field(Notification, "is_read") else []
    search_fields = ["title", "message"]
    ordering = ["-created_at"] if _model_has_field(Notification, "created_at") else ["-pk"]
    readonly_fields = ["created_at"] if _model_has_field(Notification, "created_at") else []
    date_hierarchy = "created_at" if _model_has_field(Notification, "created_at") else None
    actions = ["mark_as_read", "mark_as_unread"]

    def get_list_select_related(self, request):
        sr = []
        if _model_has_field(Notification, "related_booking_request"):
            sr.extend(
                [
                    "related_booking_request",
                    "related_booking_request__doctor",
                    "related_booking_request__doctor__user",
                ]
            )
        return tuple(dict.fromkeys(sr))

    def get_list_display(self, request):
        cols = []
        if _model_has_field(Notification, "title"):
            cols.append("title")
        if _model_has_field(Notification, "related_booking_request"):
            cols.append("related_booking_request")
        if _model_has_field(Notification, "is_read"):
            cols.append("is_read")
        if _model_has_field(Notification, "created_at"):
            cols.append("created_at")
        return cols or ["__str__"]

    def get_list_editable(self, request):
        return ("is_read",) if _model_has_field(Notification, "is_read") else ()

    @admin.action(description=_("Mark selected notifications as READ"))
    def mark_as_read(self, request, queryset):
        if not _model_has_field(Notification, "is_read"):
            self.message_user(request, _("is_read field not found."), level=messages.ERROR)
            return
        updated = queryset.filter(is_read=False).update(is_read=True)
        self.message_user(request, _("%(n)s notification(s) marked as read.") % {"n": updated})

    @admin.action(description=_("Mark selected notifications as UNREAD"))
    def mark_as_unread(self, request, queryset):
        if not _model_has_field(Notification, "is_read"):
            self.message_user(request, _("is_read field not found."), level=messages.ERROR)
            return
        updated = queryset.filter(is_read=True).update(is_read=False)
        self.message_user(request, _("%(n)s notification(s) marked as unread.") % {"n": updated})