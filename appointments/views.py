# appointments/views.py
from __future__ import annotations

import base64
import csv
import io
import json
from datetime import date, timedelta
from functools import wraps
from typing import Any
from urllib.parse import urlencode

import qrcode
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import get_default_timezone, localtime, make_aware
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.forms import CustomPasswordForm, ProfileUpdateForm
from doctor.models import Doctor
from hospital.models import Branch, Department, Hospital, StaffAssignment
from patient.forms import SecretaryPatientForm
from patient.models import Patient

# ✅ FIX: import datetime-local parsing tools used by booking form
from .forms import AppointmentForm, DATETIME_INPUT_FORMATS, DateTimeLocalInput
from .models import Appointment, AppointmentStatus, Notification, PatientBookingRequest

# Optional BookingRequestStatus for lighter builds
try:  # pragma: no cover
    from .models import BookingRequestStatus  # type: ignore
except Exception:  # pragma: no cover
    BookingRequestStatus = None  # type: ignore

User = get_user_model()

# ------------------------------------------------------------------#
#                           Helpers                                  #
# ------------------------------------------------------------------#
_LOCAL_TZ = get_default_timezone()


def _json_success(data: dict[str, Any]) -> JsonResponse:
    """Wrap a successful JSON response."""
    return JsonResponse({**data, "success": True})


def _json_error(msg: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": msg}, status=status)


def _today() -> date:
    return timezone.localdate()


def _model_has_field(model, field_name: str) -> bool:
    try:
        return any(
            getattr(f, "name", "") == field_name
            for f in model._meta.get_fields()  # type: ignore[attr-defined]
        )
    except Exception:
        return False


def _doctor_name(doc: Doctor | None) -> str:
    if not doc:
        return "Doctor"
    return (
        getattr(doc, "get_display_name", lambda: "")()
        or getattr(doc, "full_name", "")
        or doc.user.get_full_name()
        or doc.user.first_name
        or (
            doc.user.username.split("@")[0]
            if "@" in (doc.user.username or "")
            else doc.user.username
        )
        or "Doctor"
    )


def _user_name(u) -> str:
    return (
        u.get_full_name()
        or getattr(u, "first_name", "")
        or (u.username.split("@")[0] if "@" in (u.username or "") else u.username)
        or "User"
    )


def _to_local_aware(dt):
    """
    Normalize naive datetimes to local TZ without changing the wall clock.
    If already aware -> convert to local TZ.
    """
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return make_aware(dt, _LOCAL_TZ)
    return dt.astimezone(_LOCAL_TZ)


def _now_local_aware():
    """Return now in local TZ (aware)."""
    now = timezone.now()
    if timezone.is_naive(now):
        return make_aware(now, _LOCAL_TZ)
    return now.astimezone(_LOCAL_TZ)


def _user_is_secretary(user) -> bool:
    role = getattr(user, "role", None)
    if hasattr(User, "Roles"):
        try:
            return role == User.Roles.SECRETARY
        except Exception:
            pass
    return role == "secretary"


def _user_is_patient(user) -> bool:
    role = getattr(user, "role", None)
    if hasattr(User, "Roles"):
        try:
            return role == User.Roles.PATIENT
        except Exception:
            pass
    return role == "patient"


def _secretary_assigned_doctor(user) -> Doctor | None:
    """
    Return the doctor assigned to this secretary, or None if:
    - user is superuser / admin (can see all)
    - user has no assigned doctor
    - user is not a secretary
    """
    if getattr(user, "is_superuser", False):
        return None
    if not _user_is_secretary(user):
        return None

    cache_attr = "_cached_assigned_doctor_obj"
    if hasattr(user, cache_attr):
        return getattr(user, cache_attr)

    doc: Doctor | None = None

    try:
        direct = getattr(user, "assigned_doctor", None)
        if isinstance(direct, Doctor):
            doc = direct
        else:
            direct_id = getattr(user, "assigned_doctor_id", None)
            if direct_id:
                doc = Doctor.objects.select_related("user").filter(pk=direct_id).first()

        if doc is None:
            # fallback patterns (if you have secretary_profile, etc.)
            for attr in ("secretary_profile", "secretary", "profile", "staff_profile"):
                obj = getattr(user, attr, None)
                if not obj:
                    continue
                cand = getattr(obj, "doctor", None) or getattr(obj, "assigned_doctor", None)
                if isinstance(cand, Doctor):
                    doc = cand
                    break
                cand_id = getattr(obj, "doctor_id", None) or getattr(obj, "assigned_doctor_id", None)
                if cand_id:
                    doc = Doctor.objects.select_related("user").filter(pk=cand_id).first()
                    break
    except Exception:
        doc = None

    setattr(user, cache_attr, doc)
    return doc



def _active_staff_assignments(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return StaffAssignment.objects.none()

    allowed_roles = (
        StaffAssignment.Roles.HOSPITAL_ADMIN,
        StaffAssignment.Roles.SECRETARY,
        StaffAssignment.Roles.RECEPTIONIST,
    )

    return (
        StaffAssignment.objects.filter(
            user=user,
            role__in=allowed_roles,
            is_active=True,
        )
        .select_related(
            "hospital",
            "branch",
            "department",
        )
        .order_by("-is_primary", "pk")
    )


def _build_location_scope(assignments):
    scope = None

    for assignment in assignments:
        if assignment.department_id:
            current_scope = Q(department_id=assignment.department_id)
        elif assignment.branch_id:
            current_scope = Q(branch_id=assignment.branch_id)
        else:
            current_scope = Q(hospital_id=assignment.hospital_id)

        scope = current_scope if scope is None else scope | current_scope

    return scope


def _filter_appointments_for_user(qs, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    assigned_doctor = _secretary_assigned_doctor(user)
    assignments = list(_active_staff_assignments(user))

    if assignments:
        location_scope = _build_location_scope(assignments)
        qs = qs.filter(location_scope)

        if assigned_doctor is not None:
            qs = qs.filter(doctor=assigned_doctor)

        return qs.distinct()

    if assigned_doctor is not None:
        return qs.filter(doctor=assigned_doctor)

    if _user_is_secretary(user):
        return qs.none()

    return qs.none()


def _filter_booking_requests_for_user(qs, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    assigned_doctor = _secretary_assigned_doctor(user)
    assignments = list(_active_staff_assignments(user))

    if assignments:
        location_scope = _build_location_scope(assignments)
        qs = qs.filter(location_scope)

        if assigned_doctor is not None:
            qs = qs.filter(doctor=assigned_doctor)

        return qs.distinct()

    if assigned_doctor is not None:
        return qs.filter(doctor=assigned_doctor)

    if _user_is_secretary(user):
        return qs.none()

    return qs.none()


def _filter_doctors_for_user(qs, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    assigned_doctor = _secretary_assigned_doctor(user)
    assignments = list(_active_staff_assignments(user))

    if assignments:
        doctor_scope = None

        for assignment in assignments:
            current_scope = Q(
                user__hospital_assignments__role=StaffAssignment.Roles.DOCTOR,
                user__hospital_assignments__is_active=True,
            )

            if assignment.department_id:
                current_scope &= Q(
                    user__hospital_assignments__department_id=assignment.department_id
                )
            elif assignment.branch_id:
                current_scope &= Q(
                    user__hospital_assignments__branch_id=assignment.branch_id
                )
            else:
                current_scope &= Q(
                    user__hospital_assignments__hospital_id=assignment.hospital_id
                )

            doctor_scope = (
                current_scope
                if doctor_scope is None
                else doctor_scope | current_scope
            )

        qs = qs.filter(doctor_scope).distinct()

        if assigned_doctor is not None:
            qs = qs.filter(pk=assigned_doctor.pk)

        return qs

    if assigned_doctor is not None:
        return qs.filter(pk=assigned_doctor.pk)

    return qs.none()


def _restrict_appointment_form_for_user(form, user):
    if getattr(user, "is_superuser", False):
        return form

    assigned_doctor = _secretary_assigned_doctor(user)
    assignments = list(_active_staff_assignments(user))

    if assignments:
        hospital_ids = {assignment.hospital_id for assignment in assignments}
        explicit_branch_ids = {
            assignment.branch_id
            for assignment in assignments
            if assignment.branch_id
        }
        explicit_department_ids = {
            assignment.department_id
            for assignment in assignments
            if assignment.department_id
        }
        hospital_wide_ids = {
            assignment.hospital_id
            for assignment in assignments
            if not assignment.branch_id
        }
        branch_wide_ids = {
            assignment.branch_id
            for assignment in assignments
            if assignment.branch_id and not assignment.department_id
        }

        if "hospital" in form.fields:
            form.fields["hospital"].queryset = (
                form.fields["hospital"].queryset.filter(pk__in=hospital_ids)
            )

        if "branch" in form.fields:
            branch_scope = Q(pk__in=explicit_branch_ids)

            if hospital_wide_ids:
                branch_scope |= Q(hospital_id__in=hospital_wide_ids)

            form.fields["branch"].queryset = (
                form.fields["branch"].queryset.filter(branch_scope).distinct()
            )

        if "department" in form.fields:
            department_scope = Q(pk__in=explicit_department_ids)

            if branch_wide_ids:
                department_scope |= Q(branch_id__in=branch_wide_ids)

            if hospital_wide_ids:
                department_scope |= Q(
                    branch__hospital_id__in=hospital_wide_ids
                )

            form.fields["department"].queryset = (
                form.fields["department"]
                .queryset.filter(department_scope)
                .distinct()
            )

        if "doctor" in form.fields:
            form.fields["doctor"].queryset = _filter_doctors_for_user(
                form.fields["doctor"].queryset,
                user,
            )

        if not form.is_bound:
            primary_assignment = next(
                (
                    assignment
                    for assignment in assignments
                    if assignment.is_primary
                ),
                assignments[0],
            )

            form.initial.setdefault(
                "hospital",
                primary_assignment.hospital_id,
            )

            if primary_assignment.branch_id:
                form.initial.setdefault(
                    "branch",
                    primary_assignment.branch_id,
                )

            if primary_assignment.department_id:
                form.initial.setdefault(
                    "department",
                    primary_assignment.department_id,
                )

        return form

    if assigned_doctor is not None:
        if "doctor" in form.fields:
            form.fields["doctor"].queryset = Doctor.objects.filter(
                pk=assigned_doctor.pk
            )

        doctor_assignment = (
            StaffAssignment.objects.filter(
                user_id=assigned_doctor.user_id,
                role=StaffAssignment.Roles.DOCTOR,
                is_active=True,
            )
            .select_related("hospital", "branch", "department")
            .order_by("-is_primary", "pk")
            .first()
        )

        if doctor_assignment:
            if "hospital" in form.fields:
                form.fields["hospital"].queryset = Hospital.objects.filter(
                    pk=doctor_assignment.hospital_id
                )

            if "branch" in form.fields:
                form.fields["branch"].queryset = Branch.objects.filter(
                    pk=doctor_assignment.branch_id
                )

            if "department" in form.fields:
                form.fields["department"].queryset = Department.objects.filter(
                    pk=doctor_assignment.department_id
                )

            if not form.is_bound:
                form.initial.setdefault(
                    "hospital",
                    doctor_assignment.hospital_id,
                )

                if doctor_assignment.branch_id:
                    form.initial.setdefault(
                        "branch",
                        doctor_assignment.branch_id,
                    )

                if doctor_assignment.department_id:
                    form.initial.setdefault(
                        "department",
                        doctor_assignment.department_id,
                    )

        return form

    if _user_is_secretary(user):
        for field_name in (
            "hospital",
            "branch",
            "department",
            "doctor",
        ):
            if field_name in form.fields:
                form.fields[field_name].queryset = (
                    form.fields[field_name].queryset.none()
                )

    return form


def _filter_notifications_for_user(qs, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    visibility_filter = Q()
    has_visibility_rule = False

    if _model_has_field(Notification, "recipient"):
        visibility_filter |= Q(recipient=user)
        has_visibility_rule = True

    if _notif_has_related_request():
        allowed_request_ids = _filter_booking_requests_for_user(
            PatientBookingRequest.objects.all(),
            user,
        ).values_list("pk", flat=True)

        visibility_filter |= Q(
            related_booking_request_id__in=allowed_request_ids
        )
        has_visibility_rule = True

    if not has_visibility_rule:
        return qs.none()

    return qs.filter(visibility_filter).distinct()


def _parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed > 0 else None


def _scope_public_queue_queryset(qs, request):
    department_id = _parse_positive_int(request.GET.get("department"))
    branch_id = _parse_positive_int(request.GET.get("branch"))
    hospital_id = _parse_positive_int(request.GET.get("hospital"))

    if department_id:
        return qs.filter(department_id=department_id)

    if branch_id:
        return qs.filter(branch_id=branch_id)

    if hospital_id:
        return qs.filter(hospital_id=hospital_id)

    branch_ids = list(
        qs.exclude(branch_id__isnull=True)
        .values_list("branch_id", flat=True)
        .distinct()[:2]
    )

    if len(branch_ids) == 1:
        return qs.filter(branch_id=branch_ids[0])

    hospital_ids = list(
        qs.exclude(hospital_id__isnull=True)
        .values_list("hospital_id", flat=True)
        .distinct()[:2]
    )

    if len(hospital_ids) == 1:
        return qs.filter(hospital_id=hospital_ids[0])

    return qs.none()


def _doctor_specialty(doc: Doctor) -> str:
    """Safely resolve doctor's specialty from different possible field names."""
    if _model_has_field(Doctor, "speciality"):
        value = getattr(doc, "speciality", "")
    elif _model_has_field(Doctor, "specialty"):
        value = getattr(doc, "specialty", "")
    elif _model_has_field(Doctor, "specialization"):
        value = getattr(doc, "specialization", "")
    elif _model_has_field(Doctor, "department"):
        value = getattr(doc, "department", "")
    else:
        value = ""
    return str(value or "")


def _doctor_room(doc: Doctor) -> str:
    """Safely resolve doctor's room from different possible field names."""
    if _model_has_field(Doctor, "room_number"):
        value = getattr(doc, "room_number", "")
    elif _model_has_field(Doctor, "room"):
        value = getattr(doc, "room", "")
    elif _model_has_field(Doctor, "clinic_room"):
        value = getattr(doc, "clinic_room", "")
    else:
        value = ""
    return str(value or "")


def _secretary_default_status():
    """
    If your AppointmentStatus includes APPROVED/CONFIRMED/ACCEPTED, use it as default for secretary-created appointments.
    Otherwise fallback to PENDING.
    """
    for name in ("APPROVED", "CONFIRMED", "ACCEPTED"):
        if hasattr(AppointmentStatus, name):
            return getattr(AppointmentStatus, name)
    return AppointmentStatus.PENDING


def _redirect_with_query(viewname: str, *, query: dict[str, Any] | None = None, **kwargs):
    url = reverse(viewname, kwargs=kwargs or None)
    if query:
        qs = urlencode({k: v for k, v in query.items() if v is not None and v != ""})
        if qs:
            url = f"{url}?{qs}"
    return redirect(url)


def secretary_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *a, **kw):
        if (not _user_is_secretary(request.user)) and (not request.user.is_superuser):
            return HttpResponseForbidden("You do not have permission to access this page.")
        return view(request, *a, **kw)

    return wrapper


def staff_ticket_required(view):
    """
    For ticket/list screens:
    - allow secretary OR superuser
    (No frontdesk/reception roles in this build)
    """

    @wraps(view)
    @login_required
    def wrapper(request, *a, **kw):
        if request.user.is_superuser:
            return view(request, *a, **kw)
        if _user_is_secretary(request.user):
            return view(request, *a, **kw)
        return HttpResponseForbidden("You do not have permission to access this page.")

    return wrapper


def is_patient(user) -> bool:
    return _user_is_patient(user)


def _logout_other_sessions(request: HttpRequest) -> None:
    """
    Log out other sessions for THE SAME USER only.
    (Fix: never delete sessions for other users.)
    """
    current_key = request.session.session_key
    if not current_key:
        return

    user_id = str(request.user.id)
    qs = Session.objects.filter(expire_date__gte=timezone.now()).exclude(session_key=current_key)

    for s in qs:
        try:
            data = s.get_decoded()
            if str(data.get("_auth_user_id")) == user_id:
                s.delete()
        except Exception:
            continue


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _get_period_range(request: HttpRequest, default_period: str = "day") -> tuple[str, date, date]:
    """Resolve reporting period (day/week/month/custom) into [start, end] dates."""
    today = _today()
    period = (request.GET.get("period") or default_period).lower()
    if period not in {"day", "week", "month", "custom"}:
        period = default_period

    if period == "day":
        start = end = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_month = start.replace(month=start.month + 1, day=1)
        end = next_month - timedelta(days=1)
    else:  # custom
        s = _parse_iso_date(request.GET.get("start"))
        e = _parse_iso_date(request.GET.get("end"))
        start = s or today
        end = e or start
        if end < start:
            start, end = end, start

    return period, start, end


def _notif_has_related_request() -> bool:
    return _model_has_field(Notification, "related_booking_request")


def _queue_active_statuses() -> list:
    """
    Active queue statuses:
      - Always include PENDING
      - Include APPROVED/CONFIRMED/ACCEPTED if your enum has it
      - Include CALLED if exists
    """
    statuses = [AppointmentStatus.PENDING]
    for name in ("APPROVED", "CONFIRMED", "ACCEPTED"):
        if hasattr(AppointmentStatus, name):
            statuses.append(getattr(AppointmentStatus, name))
    if hasattr(AppointmentStatus, "CALLED"):
        statuses.append(getattr(AppointmentStatus, "CALLED"))
    seen = set()
    out = []
    for s in statuses:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _queue_waiting_statuses() -> list:
    """
    Statuses that are considered "waiting" (i.e., can be called next).
    - Active statuses minus CALLED
    """
    active = _queue_active_statuses()
    called = getattr(AppointmentStatus, "CALLED", None)
    if called is None:
        return active
    return [s for s in active if s != called]


def _get_patient_for_user(user) -> Patient | None:
    """
    Robust patient resolver for patient-portal endpoints.
    Tries:
      - user.patient_profile / user.patient
      - Patient.user FK if exists
    """
    p = getattr(user, "patient_profile", None) or getattr(user, "patient", None)
    if isinstance(p, Patient):
        return p
    if _model_has_field(Patient, "user"):
        return Patient.objects.filter(user=user).first()
    return None


# ------------------------------------------------------------------#
#                     Secretary Dashboard                            #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def secretary_dashboard(request: HttpRequest):
    today = _today()

    base = Appointment.objects.select_related(
        "patient",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    )
    base = _filter_appointments_for_user(base, request.user)

    todays_all = base.filter(
        scheduled_time__date=today
    ).order_by("scheduled_time")
    todays_queue = todays_all.filter(
        status__in=_queue_active_statuses()
    )

    revenue_today = 0
    if _model_has_field(Appointment, "iqd_amount"):
        revenue_today = (
            todays_all.aggregate(total=Sum("iqd_amount")).get("total")
            or 0
        )

    scoped_patient_ids = base.values_list(
        "patient_id",
        flat=True,
    ).distinct()
    pat_qs = Patient.objects.filter(pk__in=scoped_patient_ids)

    stats = {
        "patients_today": todays_all.values(
            "patient_id"
        ).distinct().count(),
        "new_patients_today": (
            pat_qs.filter(created_at__date=today).count()
            if _model_has_field(Patient, "created_at")
            else 0
        ),
        "total_patients": pat_qs.count(),
        "appointments_today": todays_all.count(),
        "revenue_today_iqd": revenue_today,
    }

    week_start = today - timedelta(days=today.weekday())
    rows = (
        base.filter(
            scheduled_time__date__range=[
                week_start,
                week_start + timedelta(days=6),
            ]
        )
        .annotate(day=TruncDate("scheduled_time"))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts = {row["day"]: row["count"] for row in rows}
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    chart = [
        counts.get(week_start + timedelta(days=index), 0)
        for index in range(7)
    ]

    assigned_doctor = _secretary_assigned_doctor(request.user)
    assigned_doctor_id = (
        assigned_doctor.id if assigned_doctor is not None else None
    )
    call_next_url = (
        reverse(
            "appointments:call_next_api",
            kwargs={"doctor_id": assigned_doctor.id},
        )
        if assigned_doctor is not None
        else ""
    )

    appointment_form = AppointmentForm()
    _restrict_appointment_form_for_user(
        appointment_form,
        request.user,
    )

    context = {
        "appointment_form": appointment_form,
        "patient_form": SecretaryPatientForm(),
        "appointments": base.order_by("-scheduled_time")[:20],
        "today_appointments": todays_queue,
        "today_appointments_all": todays_all,
        "stats": stats,
        "chart_data_json": json.dumps(
            {"labels": labels, "data": chart}
        ),
        "assigned_doctor": assigned_doctor,
        "assigned_doctor_id": assigned_doctor_id,
        "call_next_url": call_next_url,
        "queue_api_url": reverse(
            "appointments:queue_number_api"
        ),
        "recycle_bin_url": reverse(
            "appointments:appointment_recycle_bin"
        ),
    }
    return render(
        request,
        "appointments/secretary_dashboard.html",
        context,
    )


# ------------------------------------------------------------------#
#                        Appointment CRUD                            #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.add_appointment",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def create_appointment(request: HttpRequest):
    """
    Secretary-created appointments:
    - Rely on models.Appointment.save() to atomically assign queue_number.
    - Do NOT compute queue_number here to avoid race conditions.
    - If secretary is assigned to a single doctor, force that doctor.
    - ✅ After create: redirect to appointment list (NOT ticket) for faster workflow.
    """
    assigned_doctor = _secretary_assigned_doctor(request.user)
    form = AppointmentForm(
        request.POST if request.method == "POST" else None
    )
    _restrict_appointment_form_for_user(form, request.user)

    # Restrict the doctor field for legacy one-doctor secretary assignments.
    if "doctor" in form.fields and assigned_doctor is not None:
        form.fields["doctor"].queryset = Doctor.objects.filter(pk=assigned_doctor.pk)

    # Use the staff default status when the model supports it.
    if request.method == "GET" and "status" in form.fields:
        try:
            form.fields["status"].initial = _secretary_default_status()
        except Exception:
            pass

    if request.method == "POST" and form.is_valid():
        appt: Appointment = form.save(commit=False)

        # Enforce the legacy secretary-to-doctor assignment.
        if assigned_doctor is not None:
            appt.doctor = assigned_doctor

        appt.scheduled_time = _to_local_aware(appt.scheduled_time)

        # Prevent creating an appointment in the past.
        if appt.scheduled_time and appt.scheduled_time <= _now_local_aware():
            form.add_error("scheduled_time", "يرجى اختيار وقت مستقبلي.")
            messages.error(request, "⚠️ لا يمكن حجز موعد بوقت ماضي.")
            return render(request, "appointments/create_appointment.html", {"form": form})

        try:
            appt.save()
        except IntegrityError:
            messages.error(request, "❌ هذا التوقيت محجوز مسبقًا لهذا الطبيب. يرجى اختيار وقت آخر.")
            return render(request, "appointments/create_appointment.html", {"form": form})
        except ValidationError as e:
            msg = "❌ لا يمكن حفظ الموعد. يرجى التحقق من البيانات."
            if hasattr(e, "messages") and e.messages:
                msg = f"❌ {e.messages[0]}"
            messages.error(request, msg)
            return render(request, "appointments/create_appointment.html", {"form": form})

        time_part = "—"
        if appt.scheduled_time:
            time_part = localtime(appt.scheduled_time).strftime("%I:%M %p")

        qno = ""
        if getattr(appt, "queue_number", None):
            qno = f" | رقم الدور: P-{appt.queue_number:03d}"

        messages.success(
            request,
            (
                f"✅ تم حجز الموعد بنجاح للمريض: {appt.patient.full_name} "
                f"مع الدكتور/ة: {_doctor_name(appt.doctor)} "
                f"في الساعة {time_part}.{qno}"
            ),
        )

        # ✅ Redirect to list (with created=ID to highlight)
        return _redirect_with_query("appointments:appointment_list", query={"created": appt.pk})

    elif request.method == "POST":
        messages.error(request, "⚠️ لم يتم حفظ الموعد. يرجى تصحيح الأخطاء في الحقول وإعادة المحاولة.")

    return render(request, "appointments/create_appointment.html", {"form": form})


@staff_ticket_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def appointment_ticket(request: HttpRequest, pk: int):
    """
    Ticket page:
    - Allowed for secretary + superuser
    - Still scoped to secretary assigned doctor if applicable (safe)
    """
    qs = Appointment.objects.select_related("doctor__user", "patient")
    qs = _filter_appointments_for_user(qs, request.user)
    appt = get_object_or_404(qs, pk=pk)

    qr = qrcode.make(request.build_absolute_uri(), box_size=6, border=2)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")

    ctx = {
        "appointment": appt,
        "doctor_name": _doctor_name(appt.doctor),
        "doctor_spec": _doctor_specialty(appt.doctor),
        "doctor_room": _doctor_room(appt.doctor),
        "secretary_name": _user_name(request.user),
        "qr_code": base64.b64encode(buf.getvalue()).decode(),
    }
    return render(request, "appointments/appointment_ticket.html", ctx)


@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def edit_appointment(request: HttpRequest, pk: int):
    qs = Appointment.objects.all()
    qs = _filter_appointments_for_user(qs, request.user)
    appt = get_object_or_404(qs, pk=pk)

    form = AppointmentForm(
        request.POST if request.method == "POST" else None,
        instance=appt,
    )
    _restrict_appointment_form_for_user(form, request.user)

    assigned_doctor = _secretary_assigned_doctor(request.user)
    if "doctor" in form.fields and assigned_doctor is not None:
        form.fields["doctor"].queryset = Doctor.objects.filter(pk=assigned_doctor.pk)

    if request.method == "POST" and form.is_valid():
        appt = form.save(commit=False)

        if assigned_doctor is not None:
            appt.doctor = assigned_doctor

        appt.scheduled_time = _to_local_aware(appt.scheduled_time)

        # Prevent moving an appointment into the past.
        if appt.scheduled_time and appt.scheduled_time <= _now_local_aware():
            form.add_error("scheduled_time", "يرجى اختيار وقت مستقبلي.")
            messages.error(request, "⚠️ لا يمكن تحديث موعد إلى وقت ماضي.")
            return render(
                request,
                "appointments/edit_appointment.html",
                {"form": form, "appointment": appt},
            )

        try:
            appt.save()
        except IntegrityError:
            messages.error(request, "❌ هذا التوقيت محجوز مسبقًا لهذا الطبيب. يرجى اختيار وقت آخر.")
            return render(
                request,
                "appointments/edit_appointment.html",
                {"form": form, "appointment": appt},
            )
        except ValidationError as e:
            msg = "❌ لا يمكن تحديث الموعد. يرجى التحقق من البيانات."
            if hasattr(e, "messages") and e.messages:
                msg = f"❌ {e.messages[0]}"
            messages.error(request, msg)
            return render(
                request,
                "appointments/edit_appointment.html",
                {"form": form, "appointment": appt},
            )

        messages.success(request, "✅ تم تحديث بيانات الموعد بنجاح.")
        return redirect("appointments:appointment_list")

    elif request.method == "POST":
        messages.error(request, "⚠️ لم يتم تحديث الموعد. يرجى مراجعة البيانات المدخلة.")

    return render(request, "appointments/edit_appointment.html", {"form": form, "appointment": appt})


@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def cancel_appointment(request: HttpRequest, pk: int):
    """Soft cancel: forbid COMPLETED; set status=CANCELLED."""
    qs = Appointment.objects.all()
    qs = _filter_appointments_for_user(qs, request.user)
    appt = get_object_or_404(qs, pk=pk)

    if appt.status == AppointmentStatus.COMPLETED:
        messages.error(request, "❌ لا يمكن إلغاء موعد تم الانتهاء منه بالفعل.")
        return redirect("appointments:appointment_list")

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()

        update_kwargs: dict[str, object] = {"status": AppointmentStatus.CANCELLED}

        if reason and _model_has_field(Appointment, "notes"):
            stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            user_display = request.user.get_full_name() or request.user.username
            note_line = f"[Cancelled {stamp} by {user_display}] {reason}"
            existing_notes = getattr(appt, "notes", "") or ""
            new_notes = f"{existing_notes}\n{note_line}".strip()
            update_kwargs["notes"] = new_notes

        appt.status = AppointmentStatus.CANCELLED

        if "notes" in update_kwargs:
            appt.notes = update_kwargs["notes"]

        appt.save()

        messages.success(request, "✅ تم إلغاء الموعد بنجاح وتم تحديث حالة السجل في نظام ClinicHub.")
        return redirect("appointments:appointment_list")

    return render(request, "appointments/delete_confirmation.html", {"appointment": appt})


@secretary_required
@permission_required(
    "appointments.delete_appointment",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def delete_appointment(request: HttpRequest, pk: int):
    """
    ✅ Soft Delete (Recycle Bin):
    - Secretary / superuser can delete (soft) -> moves record to Recycle Bin
    - Permanent delete is ONLY from recycle-bin hard delete endpoint (superuser only)
    """
    qs = Appointment.objects.all()
    qs = _filter_appointments_for_user(qs, request.user)
    appt = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        # soft delete (moves to recycle bin)
        appt.delete(user=request.user)
        messages.success(request, "🗑️ تم نقل الموعد إلى سلة المحذوفات (Recycle Bin).")
        return redirect("appointments:appointment_list")

    return render(request, "appointments/delete_confirmation.html", {"appointment": appt})


# ------------------------------------------------------------------#
#                 Recycle Bin (Appointments)                         #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def appointment_recycle_bin(request: HttpRequest):
    """
    Show deleted appointments (soft-deleted) for secretary/superuser.
    Scoped to assigned doctor if configured.
    """
    qs = Appointment.deleted_objects.select_related(
        "patient",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    ).order_by("-deleted_at", "-pk")
    qs = _filter_appointments_for_user(qs, request.user)

    q = (request.GET.get("q") or "").strip()
    if q:
        notes_q = Q()
        if _model_has_field(Appointment, "notes"):
            notes_q = Q(notes__icontains=q)
        qs = qs.filter(
            Q(patient__full_name__icontains=q)
            | Q(doctor__user__first_name__icontains=q)
            | Q(doctor__user__last_name__icontains=q)
            | notes_q
        )

    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "appointments/appointment_recycle_bin.html",
        {
            "deleted_appointments": page,
            "search_query": q,
        },
    )


@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_POST
def restore_appointment(request: HttpRequest, pk: int):
    """
    Restore a soft-deleted appointment.
    Uses Appointment.restore() (model-level) to re-run validations/queue logic.
    """
    qs = Appointment.all_objects.select_related(
        "patient",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    )
    qs = _filter_appointments_for_user(qs, request.user)
    appt = get_object_or_404(qs, pk=pk)

    if not getattr(appt, "is_deleted", False):
        messages.info(request, "ℹ️ هذا الموعد ليس ضمن سلة المحذوفات.")
        return redirect("appointments:appointment_recycle_bin")

    try:
        appt.restore()
        messages.success(request, "✅ تم استرجاع الموعد بنجاح.")
    except IntegrityError:
        messages.error(
            request,
            "❌ لا يمكن استرجاع الموعد لأن هناك تعارض (نفس الطبيب ونفس الوقت موجود). "
            "رجاءً غيّري وقت الموعد أو احذفي الموعد المتعارض."
        )
    except ValidationError as e:
        msg = "❌ لا يمكن استرجاع الموعد. يرجى التحقق من البيانات."
        if hasattr(e, "messages") and e.messages:
            msg = f"❌ {e.messages[0]}"
        messages.error(request, msg)

    return redirect("appointments:appointment_recycle_bin")


@secretary_required
@permission_required(
    "appointments.delete_appointment",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def hard_delete_appointment(request: HttpRequest, pk: int):
    """
    Permanent delete (SUPERUSER ONLY) from Recycle Bin.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Hard delete is restricted to administrators only.")

    qs = Appointment.all_objects.select_related(
        "patient",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    )
    appt = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        appt.delete(hard=True)
        messages.success(request, "🗑️ تم حذف الموعد نهائيًا (Permanent Delete).")
        return redirect("appointments:appointment_recycle_bin")

    # Reuse confirmation template
    return render(
        request,
        "appointments/delete_confirmation.html",
        {"appointment": appt},
    )


@staff_ticket_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def appointment_list(request: HttpRequest):
    """
    Appointment list:
    - Allow secretary + superuser
    - Still scope to assigned doctor for secretary if configured
    - Supports ?created=<id> to highlight newly created appointment row in UI
    """
    sort = request.GET.get("sort", "scheduled_time")
    fld = {
        "patient": "patient__full_name",
        "doctor": "doctor__user__first_name",
        "scheduled_time": "scheduled_time",
    }.get(sort, "scheduled_time")

    qs = Appointment.objects.select_related(
        "patient",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    )
    qs = _filter_appointments_for_user(qs, request.user)

    status_key = (request.GET.get("status") or "all").lower()
    status_map = {
        "pending": AppointmentStatus.PENDING,
        "completed": AppointmentStatus.COMPLETED,
        "cancelled": AppointmentStatus.CANCELLED,
    }
    if hasattr(AppointmentStatus, "CALLED"):
        status_map["called"] = getattr(AppointmentStatus, "CALLED")
    for name, key in (("APPROVED", "approved"), ("CONFIRMED", "confirmed"), ("ACCEPTED", "accepted")):
        if hasattr(AppointmentStatus, name):
            status_map[key] = getattr(AppointmentStatus, name)

    if status_key in status_map:
        qs = qs.filter(status=status_map[status_key])

    q = (request.GET.get("q") or "").strip()
    if q:
        notes_q = Q()
        if _model_has_field(Appointment, "notes"):
            notes_q = Q(notes__icontains=q)
        qs = qs.filter(
            Q(patient__full_name__icontains=q)
            | Q(doctor__user__first_name__icontains=q)
            | Q(doctor__user__last_name__icontains=q)
            | notes_q
        )

    created_id = request.GET.get("created")
    created_int: int | None = None
    if created_id:
        try:
            created_int = int(created_id)
        except Exception:
            created_int = None

    page = Paginator(qs.order_by(f"-{fld}"), 10).get_page(request.GET.get("page"))
    return render(
        request,
        "appointments/appointment_list.html",
        {
            "appointments": page,
            "search_query": q,
            "current_sort": sort,
            "current_status": status_key,
            "created_id": created_int,  # ✅ highlight support
            "recycle_bin_url": reverse("appointments:appointment_recycle_bin"),
        },
    )


# ------------------------------------------------------------------#
#                Patient Portal Booking (IN-APP)                    #
# ------------------------------------------------------------------#
class _PatientPortalBookingForm(forms.ModelForm):
    """Minimal form for logged-in patients: choose time only."""

    # ✅ FIX: accept HTML5 datetime-local value "YYYY-MM-DDTHH:MM"
    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=DATETIME_INPUT_FORMATS,
        required=True,
    )

    class Meta:
        model = Appointment
        fields = ["scheduled_time"]

    def __init__(self, *args, doctor: Doctor | None = None, **kwargs):
        self.doctor = doctor
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("scheduled_time")
        if st:
            st_aware = _to_local_aware(st)
            if st_aware <= _now_local_aware():
                self.add_error("scheduled_time", "Please choose a future time.")
            cleaned["scheduled_time"] = st_aware
        # Do not block conflicts here; secretary will finalize actual slot
        return cleaned


@login_required
@require_http_methods(["GET", "POST"])
def book_patient(request: HttpRequest, doctor_id: int):
    """
    Patient books INSIDE the portal:
    - If BookingRequestStatus exists, create PatientBookingRequest (PENDING/REQUESTED).
    - Otherwise, fallback to creating an Appointment with PENDING.
    """
    if not is_patient(request.user):
        return HttpResponseForbidden("Patients only.")

    doctor = get_object_or_404(Doctor, pk=doctor_id)
    patient = _get_patient_for_user(request.user)
    if not patient:
        return HttpResponseForbidden("Patient profile not found.")

    if request.method == "POST":
        form = _PatientPortalBookingForm(request.POST, doctor=doctor)
        if form.is_valid():
            sched = form.cleaned_data["scheduled_time"]

            if BookingRequestStatus:
                br_kwargs: dict[str, object] = {"doctor": doctor}

                full_name = patient.full_name or request.user.get_full_name() or request.user.username
                contact = (
                    getattr(patient, "phone", "")
                    or getattr(patient, "mobile", "")
                    or request.user.email
                    or ""
                )
                dob = getattr(patient, "date_of_birth", None)

                if _model_has_field(PatientBookingRequest, "full_name"):
                    br_kwargs["full_name"] = full_name
                if _model_has_field(PatientBookingRequest, "contact_info"):
                    br_kwargs["contact_info"] = contact
                if _model_has_field(PatientBookingRequest, "date_of_birth"):
                    br_kwargs["date_of_birth"] = dob
                if _model_has_field(PatientBookingRequest, "scheduled_time"):
                    br_kwargs["scheduled_time"] = sched

                status_val = getattr(BookingRequestStatus, "PENDING", None) or getattr(
                    BookingRequestStatus, "REQUESTED", None
                )
                if status_val is not None and _model_has_field(PatientBookingRequest, "status"):
                    br_kwargs["status"] = status_val

                if _model_has_field(PatientBookingRequest, "patient"):
                    br_kwargs["patient"] = patient
                if _model_has_field(PatientBookingRequest, "user"):
                    br_kwargs["user"] = request.user

                PatientBookingRequest.objects.create(**br_kwargs)

                messages.success(request, "Your request was sent and is pending secretary approval.")
                return redirect("patient:dashboard")

            # Fallback: create a real Appointment as PENDING
            appt = Appointment(
                patient=patient,
                doctor=doctor,
                scheduled_time=sched,
                status=getattr(AppointmentStatus, "PENDING", "pending"),
                queue_number=None,
            )
            try:
                appt.save()
            except IntegrityError:
                messages.error(request, "❌ This time slot is already booked for this doctor.")
                return redirect("appointments:my_appointments")
            except ValidationError as e:
                msg = "❌ Cannot create appointment."
                if hasattr(e, "messages") and e.messages:
                    msg = f"❌ {e.messages[0]}"
                messages.error(request, msg)
                return redirect("appointments:my_appointments")

            # Optional notification (best-effort)
            try:
                Notification.objects.create(
                    recipient=getattr(doctor, "user", None),
                    notification_type=Notification.Types.BOOKING_REQUEST,
                    title="New appointment",
                    message=(
                        f"{patient.full_name} booked {_doctor_name(doctor)} at "
                        f"{localtime(sched):%Y-%m-%d %H:%M}"
                    ),
                )
            except Exception:
                pass

            messages.success(request, "Your request was sent and is pending approval.")
            return redirect("appointments:my_appointments")

        # ✅ show a friendly message if invalid
        messages.error(request, "❌ Please correct the errors in the selected date/time.")

    else:
        form = _PatientPortalBookingForm(doctor=doctor)

    return render(
        request,
        "appointments/book_patient.html",
        {"form": form, "doctor": doctor, "patient": patient},
    )


@login_required
@require_GET
def my_appointments(request: HttpRequest):
    """
    Show actual Appointments + (if enabled) PENDING/REQUESTED PatientBookingRequests
    that belong to the logged-in patient.
    """
    if not is_patient(request.user):
        return HttpResponseForbidden("Patients only.")

    patient = _get_patient_for_user(request.user)
    if not patient:
        return HttpResponseForbidden("Patient profile not found.")

    appointments = (
        Appointment.objects.filter(patient=patient)
        .select_related(
            "doctor",
            "doctor__user",
            "hospital",
            "branch",
            "department",
        )
        .order_by("-scheduled_time")
    )

    booking_requests: list[PatientBookingRequest] = []
    if BookingRequestStatus:
        q = PatientBookingRequest.objects.all()

        if _model_has_field(PatientBookingRequest, "status"):
            if hasattr(BookingRequestStatus, "PENDING"):
                q = q.filter(status=BookingRequestStatus.PENDING)
            elif hasattr(BookingRequestStatus, "REQUESTED"):
                q = q.filter(status=BookingRequestStatus.REQUESTED)

        if _model_has_field(PatientBookingRequest, "patient"):
            q = q.filter(patient=patient)
        elif _model_has_field(PatientBookingRequest, "user"):
            q = q.filter(user=request.user)
        else:
            lookups = Q()
            phone = getattr(patient, "phone", None) or getattr(patient, "mobile", None)
            if phone and _model_has_field(PatientBookingRequest, "contact_info"):
                lookups |= Q(contact_info__icontains=str(phone))
            if request.user.email and _model_has_field(PatientBookingRequest, "contact_info"):
                lookups |= Q(contact_info__icontains=request.user.email)
            display_name = patient.full_name or request.user.get_full_name() or request.user.username
            if display_name and _model_has_field(PatientBookingRequest, "full_name"):
                lookups |= Q(full_name__icontains=display_name)
            if lookups:
                q = q.filter(lookups)

        has_submitted_at = _model_has_field(PatientBookingRequest, "submitted_at")
        q = q.select_related("doctor", "doctor__user").order_by(
            "-submitted_at" if has_submitted_at else "-scheduled_time"
        )
        booking_requests = list(q[:20])

    return render(
        request,
        "appointments/my_appointments.html",
        {"appointments": appointments, "booking_requests": booking_requests},
    )


# ------------------------------------------------------------------#
#           Approving appointments / booking requests               #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_POST
def approve_appointment(request: HttpRequest, pk: int):
    """Backwards-compat route name – delegates to confirm_appointment."""
    return confirm_appointment(request, pk)


@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_POST
def confirm_appointment(request: HttpRequest, pk: int):
    """
    Confirm an Appointment:
    - If it's cancelled or completed, refuse.
    - Otherwise, set to secretary default status (Approved/Confirmed if exists) else Pending.
    """
    qs = _filter_appointments_for_user(Appointment.objects.all(), request.user)
    appt = get_object_or_404(qs, pk=pk)

    if appt.status == AppointmentStatus.CANCELLED:
        messages.error(request, "❌ لا يمكن تأكيد موعد تم إلغاؤه.")
    elif appt.status == AppointmentStatus.COMPLETED:
        messages.error(request, "❌ لا يمكن تأكيد موعد مكتمل. يرجى إنشاء موعد جديد إذا لزم الأمر.")
    else:
        appt.status = _secretary_default_status()
        appt.save(update_fields=["status"])
        messages.success(request, "✅ تم تأكيد الموعد وتحديث حالته في نظام ClinicHub.")
    return redirect("appointments:appointment_list")


@secretary_required
@permission_required(
    "appointments.change_patientbookingrequest",
    raise_exception=True,
)
@require_POST
def approve_booking_request(request: HttpRequest, pk: int):
    """
    Convert a PatientBookingRequest -> Appointment and mark request as confirmed.
    """
    if not BookingRequestStatus:
        return _json_error("Booking requests are not enabled.", status=400)

    # ✅ scope the request itself (prevents leakage by ID guessing)
    br_qs = _filter_booking_requests_for_user(PatientBookingRequest.objects.all(), request.user)
    br = get_object_or_404(br_qs, pk=pk)

    patient_obj: Patient | None = None
    if _model_has_field(PatientBookingRequest, "patient") and getattr(br, "patient", None):
        patient_obj = br.patient  # type: ignore[attr-defined]
    elif _model_has_field(PatientBookingRequest, "user") and getattr(br, "user", None):
        patient_obj = Patient.objects.filter(user=br.user).first()  # type: ignore[attr-defined]

    if not patient_obj:
        qs_pat = Patient.objects.all()
        contact = getattr(br, "contact_info", None)

        if contact:
            look = Q()
            if _model_has_field(Patient, "mobile"):
                look |= Q(mobile__icontains=str(contact))
            if _model_has_field(Patient, "phone"):
                look |= Q(phone__icontains=str(contact))
            if _model_has_field(Patient, "user") and _model_has_field(User, "email"):
                look |= Q(user__email__iexact=str(contact))
            if look:
                qs_pat = qs_pat.filter(look)

        if (not qs_pat.exists()) and getattr(br, "full_name", None) and _model_has_field(Patient, "full_name"):
            qs_pat = Patient.objects.filter(full_name__icontains=br.full_name)

        patient_obj = qs_pat.first()

    if not patient_obj:
        messages.error(
            request,
            "⚠️ لا يمكن الاعتماد: لم يتم العثور على سجل المريض أو ربطه. يرجى إنشاء الموعد يدويًا.",
        )
        return redirect("appointments:secretary_dashboard")

    scheduled_time = _to_local_aware(getattr(br, "scheduled_time", None))
    if not scheduled_time:
        messages.error(request, "⚠️ لا يمكن اعتماد الطلب لأن وقت الحجز غير موجود.")
        return redirect("appointments:booking_requests_list")

    already_existing = False
    appt: Appointment | None = None

    try:
        with transaction.atomic():
            # ✅ treat cancelled as not-existing for approval purposes
            appt = (
                Appointment.objects.filter(
                    doctor=br.doctor,
                    patient=patient_obj,
                    scheduled_time=scheduled_time,
                )
                .exclude(status=AppointmentStatus.CANCELLED)
                .first()
            )

            if appt:
                already_existing = True
            else:
                conflict = (
                    Appointment.objects.filter(
                        doctor=br.doctor,
                        scheduled_time=scheduled_time,
                    )
                    .exclude(status=AppointmentStatus.CANCELLED)
                    .exclude(patient=patient_obj)
                    .exists()
                )
                if conflict:
                    messages.error(request, "⚠️ لا يمكن اعتماد هذا الطلب، لأن هذا التوقيت محجوز لمريض آخر.")
                    return redirect("appointments:booking_requests_list")

                appt = Appointment.objects.create(
                    patient=patient_obj,
                    doctor=br.doctor,
                    hospital_id=getattr(br, "hospital_id", None),
                    branch_id=getattr(br, "branch_id", None),
                    department_id=getattr(br, "department_id", None),
                    scheduled_time=scheduled_time,
                    status=_secretary_default_status(),
                )

            # Update request status best-effort
            try:
                if _model_has_field(PatientBookingRequest, "status"):
                    if hasattr(BookingRequestStatus, "CONFIRMED"):
                        br.status = BookingRequestStatus.CONFIRMED
                        br.save(update_fields=["status"])
                    elif hasattr(BookingRequestStatus, "APPROVED"):
                        br.status = BookingRequestStatus.APPROVED
                        br.save(update_fields=["status"])
            except Exception:
                pass

    except ValidationError as e:
        error_msg = None
        if hasattr(e, "message_dict"):
            msgs = e.message_dict.get("scheduled_time")
            if isinstance(msgs, (list, tuple)) and msgs:
                error_msg = msgs[0]

        if not error_msg:
            error_msg = "لا يمكن اعتماد هذا التوقيت لهذا الطبيب، لأنه محجوز بالفعل أو غير صالح."

        messages.error(request, f"⚠️ لم يتم اعتماد طلب الحجز: {error_msg}")
        return redirect("appointments:booking_requests_list")

    if already_existing:
        messages.success(request, "✅ تم اعتماد طلب الحجز. تم العثور على الموعد مسبقًا وربطه بالطلب.")
    else:
        messages.success(request, "✅ تم اعتماد طلب الحجز وإنشاء موعد في نظام ClinicHub.")

    if _notif_has_related_request():
        Notification.objects.filter(related_booking_request=br).update(is_read=True)

    return redirect("appointments:appointment_list")


# ------------------------------------------------------------------#
#            Booking Requests List (secretary page)                 #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.view_patientbookingrequest",
    raise_exception=True,
)
@require_GET
def booking_requests_list(request: HttpRequest):
    """
    Display external booking requests and allow staff to review them.
    Related unread notifications are marked as read when the page opens.
    """
    if not BookingRequestStatus:
        qs = PatientBookingRequest.objects.none()
    else:
        qs = PatientBookingRequest.objects.all()

        if _model_has_field(PatientBookingRequest, "status"):
            pending_status = getattr(BookingRequestStatus, "PENDING", None)
            requested_status = getattr(BookingRequestStatus, "REQUESTED", None)

            if pending_status and requested_status:
                qs = qs.filter(status__in=[pending_status, requested_status])
            elif pending_status:
                qs = qs.filter(status=pending_status)
            elif requested_status:
                qs = qs.filter(status=requested_status)

        qs = _filter_booking_requests_for_user(qs, request.user)

        if _model_has_field(PatientBookingRequest, "submitted_at"):
            qs = qs.order_by("-submitted_at")
        else:
            qs = qs.order_by("-scheduled_time")

    if _notif_has_related_request():
        notifs_qs = Notification.objects.filter(
            is_read=False
        ).exclude(
            related_booking_request__isnull=True
        )
        notifs_qs = _filter_notifications_for_user(
            notifs_qs,
            request.user,
        )
        notifs_qs.update(is_read=True)

    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "appointments/booking_requests_list.html", {"requests": page})


# ------------------------------------------------------------------#
#                       Secretary Reports                           #
# ------------------------------------------------------------------#
@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def secretary_reports(request: HttpRequest):
    """
    Analytic reports view used by the secretary 'Reports' page.
    All data is automatically scoped to the secretary's assigned doctor (if any).
    """
    period, start, end = _get_period_range(request)

    base_qs = Appointment.objects.filter(
        scheduled_time__date__range=(start, end)
    ).select_related("patient", "doctor__user")
    base_qs = _filter_appointments_for_user(base_qs, request.user)

    total = base_qs.count()
    completed = base_qs.filter(status=AppointmentStatus.COMPLETED).count()
    cancelled = base_qs.filter(status=AppointmentStatus.CANCELLED).count()
    pending = base_qs.filter(status=AppointmentStatus.PENDING).count()
    called = (
        base_qs.filter(status=getattr(AppointmentStatus, "CALLED")).count()
        if hasattr(AppointmentStatus, "CALLED")
        else 0
    )

    revenue = 0
    if _model_has_field(Appointment, "iqd_amount"):
        revenue = base_qs.aggregate(total=Sum("iqd_amount")).get("total") or 0

    if _model_has_field(Patient, "created_at"):
        patient_ids = base_qs.values_list("patient_id", flat=True).distinct()
        new_patients = (
            Patient.objects.filter(created_at__date__range=(start, end), id__in=patient_ids)
            .distinct()
            .count()
        )
    else:
        new_patients = 0

    summary = {
        "total": total,
        "completed": completed,
        "cancelled": cancelled,
        "pending": pending,
        "called": called,
        "revenue": revenue,
        "new_patients": new_patients,
    }

    if _model_has_field(Appointment, "iqd_amount"):
        daily_qs = (
            base_qs.annotate(day=TruncDate("scheduled_time"))
            .values("day")
            .annotate(count=Count("id"), revenue=Sum("iqd_amount"))
            .order_by("day")
        )
    else:
        daily_qs = (
            base_qs.annotate(day=TruncDate("scheduled_time"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

    daily = [
        {
            "day": row["day"].strftime("%Y-%m-%d") if isinstance(row["day"], date) else str(row["day"]),
            "count": row["count"],
            "revenue": row.get("revenue") or 0,
        }
        for row in daily_qs
    ]

    if _model_has_field(Appointment, "iqd_amount"):
        top_qs = (
            base_qs.values("doctor__user__first_name", "doctor__user__last_name")
            .annotate(count=Count("id"), rev=Sum("iqd_amount"))
            .order_by("-count")[:5]
        )
    else:
        top_qs = (
            base_qs.values("doctor__user__first_name", "doctor__user__last_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

    top_doctors = list(top_qs)
    appointments = base_qs.order_by("scheduled_time")

    ctx = {
        "period": period,
        "start": start,
        "end": end,
        "summary": summary,
        "daily": daily,
        "top_doctors": top_doctors,
        "appointments": appointments,
    }
    return render(request, "appointments/secretary_reports.html", ctx)


@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def reports_export(request: HttpRequest):
    """
    Export appointments in the selected period to CSV or XLSX.
    Scoped automatically to secretary's assigned doctor (if any).

    IMPORTANT: CSV is written with UTF-8 BOM so Arabic appears correctly in Excel.
    """
    fmt = (request.GET.get("format") or "csv").lower()
    _period, start, end = _get_period_range(request)

    qs = (
        Appointment.objects.filter(scheduled_time__date__range=(start, end))
        .select_related("patient", "doctor__user")
        .order_by("scheduled_time")
    )
    qs = _filter_appointments_for_user(qs, request.user)

    headers = [
        "ID",
        "Date",
        "Time",
        "Hospital",
        "Branch",
        "Department",
        "Doctor",
        "Patient",
        "Status",
        "IQD",
    ]
    rows: list[list[object]] = []

    for a in qs:
        dt = _to_local_aware(a.scheduled_time)
        dt_local = localtime(dt) if dt else None
        date_str = dt_local.strftime("%Y-%m-%d") if dt_local else ""
        time_str = dt_local.strftime("%H:%M") if dt_local else ""
        status_label = a.get_status_display() if hasattr(a, "get_status_display") else str(a.status)
        amount = getattr(a, "iqd_amount", None) or 0
        rows.append(
            [
                a.id,
                date_str,
                time_str,
                getattr(a.hospital, "name", ""),
                getattr(a.branch, "name", ""),
                getattr(a.department, "name", ""),
                _doctor_name(a.doctor),
                a.patient.full_name,
                status_label,
                amount,
            ]
        )

    filename_base = f"clinichub_reports_{start:%Y%m%d}_{end:%Y%m%d}"

    if fmt == "xlsx":
        try:
            import openpyxl
            from openpyxl.utils import get_column_letter
        except ImportError:
            fmt = "csv"

    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Appointments"
        ws.append(headers)
        for row in rows:
            ws.append(row)

        for col_idx, header in enumerate(headers, start=1):
            max_len = max([len(str(header))] + [len(str(r[col_idx - 1])) for r in (rows or [[""]])])
            ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 2

        out = io.BytesIO()
        wb.save(out)
        out.seek(0)

        resp = HttpResponse(
            out.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="{filename_base}.xlsx"'
        return resp

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename_base}.csv"'
    resp.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(resp)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return resp


# ------------------------------------------------------------------#
#                  Public vs Internal Queue Snapshots               #
# ------------------------------------------------------------------#
def _queue_doctors_queryset_for(user=None, doctor_ids=None):
    qs = Doctor.objects.select_related("user").order_by("id")

    if user is not None:
        qs = _filter_doctors_for_user(qs, user)

    if doctor_ids is not None:
        qs = qs.filter(pk__in=doctor_ids)

    limit = getattr(
        settings,
        "QUEUE_DISPLAY_DOCTORS_LIMIT",
        None,
    )

    if isinstance(limit, int) and limit > 0:
        qs = qs[:limit]

    return qs


def _queue_snapshot_internal(user=None) -> list[dict]:
    """
    INTERNAL snapshot (PHI included) – for authenticated secretary endpoints/APIs.
    If a secretary is linked to one doctor, only that doctor is returned.
    """
    today = _today()
    default_mins = int(getattr(settings, "APPOINTMENT_DURATION_MINUTES", 15) or 15)

    appts_qs = (
        Appointment.objects.filter(
            scheduled_time__date=today,
            status__in=_queue_active_statuses(),
        )
        .select_related("patient", "doctor__user")
        .order_by("scheduled_time")
    )
    appts_qs = _filter_appointments_for_user(appts_qs, user) if user is not None else appts_qs
    appts = list(appts_qs)

    doctors = list(_queue_doctors_queryset_for(user=user))

    by_doc: dict[int, list[Appointment]] = {}
    for a in appts:
        by_doc.setdefault(a.doctor_id, []).append(a)

    queues: list[dict] = []
    for d in doctors:
        today_appts = by_doc.get(d.id, [])

        # ✅ prefer CALLED as current if exists
        current_obj = None
        if hasattr(AppointmentStatus, "CALLED"):
            for a in today_appts:
                if a.status == getattr(AppointmentStatus, "CALLED"):
                    current_obj = a
                    break
        if current_obj is None and today_appts:
            current_obj = today_appts[0]

        waiting_objs = [a for a in today_appts if (current_obj is None or a.id != current_obj.id)]

        current = None
        waiting = []

        if current_obj:
            st = _to_local_aware(current_obj.scheduled_time)
            current = {
                "id": current_obj.id,
                "number": f"P-{current_obj.queue_number:03d}" if current_obj.queue_number else "-",
                "patient_name": current_obj.patient.full_name,
                "time": localtime(st).strftime("%H:%M") if st else "",
                "status": str(current_obj.status),
            }

        for w in waiting_objs:
            stw = _to_local_aware(w.scheduled_time)
            waiting.append(
                {
                    "id": w.id,
                    "number": f"P-{w.queue_number:03d}" if w.queue_number else "-",
                    "patient_name": w.patient.full_name,
                    "time": localtime(stw).strftime("%H:%M") if stw else "",
                    "status": str(w.status),
                }
            )

        queues.append(
            {
                "doctor_id": d.id,
                "doctor_name": _doctor_name(d),
                "status": "available" if today_appts else "on_break",
                "current": current,
                "waiting": waiting,
                # backward-compatible keys
                "current_patient": current,
                "waiting_list": waiting,
                "avg_time": default_mins,
            }
        )

    return queues


def _queue_snapshot_public(request: HttpRequest) -> list[dict]:
    today = _today()
    default_mins = int(
        getattr(
            settings,
            "APPOINTMENT_DURATION_MINUTES",
            15,
        )
        or 15
    )

    public_qs = (
        Appointment.objects.filter(
            scheduled_time__date=today,
            status__in=_queue_active_statuses(),
        )
        .select_related(
            "patient",
            "doctor__user",
            "hospital",
            "branch",
            "department",
        )
        .order_by("scheduled_time")
    )
    public_qs = _scope_public_queue_queryset(
        public_qs,
        request,
    )
    appointments = list(public_qs)

    doctor_ids = {
        appointment.doctor_id
        for appointment in appointments
    }
    doctors = list(
        _queue_doctors_queryset_for(
            doctor_ids=doctor_ids,
        )
    )

    by_doctor: dict[int, list[Appointment]] = {}

    for appointment in appointments:
        by_doctor.setdefault(
            appointment.doctor_id,
            [],
        ).append(appointment)

    queues: list[dict] = []

    for doctor in doctors:
        today_appointments = by_doctor.get(doctor.id, [])

        current_object = None

        if hasattr(AppointmentStatus, "CALLED"):
            called_status = getattr(
                AppointmentStatus,
                "CALLED",
            )

            for appointment in today_appointments:
                if appointment.status == called_status:
                    current_object = appointment
                    break

        if current_object is None and today_appointments:
            current_object = today_appointments[0]

        waiting_objects = [
            appointment
            for appointment in today_appointments
            if (
                current_object is None
                or appointment.id != current_object.id
            )
        ]

        current = None
        waiting = []

        if current_object:
            scheduled_time = _to_local_aware(
                current_object.scheduled_time
            )
            current = {
                "number": (
                    f"P-{current_object.queue_number:03d}"
                    if current_object.queue_number
                    else "-"
                ),
                "time": (
                    localtime(scheduled_time).strftime("%H:%M")
                    if scheduled_time
                    else ""
                ),
                "status": str(current_object.status),
            }

        for waiting_object in waiting_objects:
            scheduled_time = _to_local_aware(
                waiting_object.scheduled_time
            )
            waiting.append(
                {
                    "number": (
                        f"P-{waiting_object.queue_number:03d}"
                        if waiting_object.queue_number
                        else "-"
                    ),
                    "time": (
                        localtime(scheduled_time).strftime("%H:%M")
                        if scheduled_time
                        else ""
                    ),
                    "status": str(waiting_object.status),
                }
            )

        queues.append(
            {
                "doctor_id": doctor.id,
                "doctor_name": _doctor_name(doctor),
                "status": (
                    "available"
                    if today_appointments
                    else "on_break"
                ),
                "current": current,
                "waiting": waiting,
                "avg_time": default_mins,
            }
        )

    return queues


@require_GET
@cache_control(
    no_cache=True,
    no_store=True,
    must_revalidate=True,
)
def queue_display(request: HttpRequest):
    return render(
        request,
        "appointments/queue_display.html",
        {"queues": _queue_snapshot_public(request)},
    )


@require_GET
@cache_control(
    no_cache=True,
    no_store=True,
    must_revalidate=True,
)
def queue_public_api(request: HttpRequest):
    return _json_success(
        {"queues": _queue_snapshot_public(request)}
    )


@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def queue_number_api(request: HttpRequest):
    return _json_success({"queues": _queue_snapshot_internal(request.user)})


@secretary_required
@permission_required(
    "appointments.change_appointment",
    raise_exception=True,
)
@require_POST
def call_next_api(request: HttpRequest, doctor_id: int):
    """
    ✅ Call button logic (smart):
    - If CALLED status exists:
        1) complete the currently CALLED appointment (if any)
        2) mark the next WAITING appointment as CALLED
    - Else (no CALLED in your model):
        - just complete the next WAITING appointment
    """
    today = _today()

    assigned_doctor = _secretary_assigned_doctor(request.user)
    if assigned_doctor is not None and assigned_doctor.id != doctor_id:
        return _json_error("You cannot control the queue of another doctor.", status=403)

    # Parse optional appointment_id from POST or JSON
    appt_id_raw = ""
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            appt_id_raw = str(payload.get("appointment_id") or "").strip()
        except Exception:
            appt_id_raw = ""
    else:
        appt_id_raw = (request.POST.get("appointment_id") or "").strip()

    appt_id: int | None = None
    if appt_id_raw:
        try:
            appt_id = int(appt_id_raw)
        except Exception:
            appt_id = None

    has_called = hasattr(AppointmentStatus, "CALLED")
    called_status = getattr(AppointmentStatus, "CALLED", None)
    completed_status = AppointmentStatus.COMPLETED

    waiting_statuses = _queue_waiting_statuses()

    updated: dict[str, Any] = {}

    with transaction.atomic():
        accessible_appointment_ids = _filter_appointments_for_user(
            Appointment.objects.filter(
                doctor_id=doctor_id,
                scheduled_time__date=today,
            ),
            request.user,
        ).values("pk")

        base = (
            Appointment.objects.select_for_update(of=("self",))
            .filter(
                pk__in=Subquery(accessible_appointment_ids),
            )
            .select_related(
                "patient",
                "doctor__user",
                "hospital",
                "branch",
                "department",
            )
            .order_by("scheduled_time", "pk")
        )

        if has_called:
            current_called = base.filter(status=called_status).first()
            if current_called:
                Appointment.objects.filter(
                    pk=current_called.pk
                ).update(status=completed_status)

            next_qs = base.filter(status__in=waiting_statuses)
            nxt = (
                next_qs.filter(pk=appt_id).first()
                if appt_id
                else None
            )
            if not nxt:
                nxt = next_qs.first()

            if not nxt:
                return _json_error(
                    "No waiting appointments for this doctor.",
                    status=404,
                )

            Appointment.objects.filter(pk=nxt.pk).update(
                status=called_status
            )
            st = _to_local_aware(nxt.scheduled_time)
            updated = {
                "id": nxt.pk,
                "status": str(called_status),
                "patient": getattr(nxt.patient, "full_name", ""),
                "time": (
                    localtime(st).strftime("%H:%M")
                    if st
                    else ""
                ),
                "number": (
                    f"P-{nxt.queue_number:03d}"
                    if nxt.queue_number
                    else "-"
                ),
            }

        else:
            next_qs = base.filter(status__in=waiting_statuses)
            nxt = (
                next_qs.filter(pk=appt_id).first()
                if appt_id
                else None
            )
            if not nxt:
                nxt = next_qs.first()

            if not nxt:
                return _json_error(
                    "No waiting appointments for this doctor.",
                    status=404,
                )

            Appointment.objects.filter(pk=nxt.pk).update(
                status=completed_status
            )
            st = _to_local_aware(nxt.scheduled_time)
            updated = {
                "id": nxt.pk,
                "status": str(completed_status),
                "patient": getattr(nxt.patient, "full_name", ""),
                "time": (
                    localtime(st).strftime("%H:%M")
                    if st
                    else ""
                ),
                "number": (
                    f"P-{nxt.queue_number:03d}"
                    if nxt.queue_number
                    else "-"
                ),
            }

    return _json_success({"updated": updated, "queues": _queue_snapshot_internal(request.user)})


@secretary_required
@permission_required(
    "appointments.view_appointment",
    raise_exception=True,
)
@require_GET
def current_patient_api(request: HttpRequest):
    now = _now_local_aware()
    today = _today()

    active_statuses = _queue_active_statuses()
    waiting_statuses = _queue_waiting_statuses()

    pend_qs = (
        Appointment.objects.filter(scheduled_time__date=today, status__in=active_statuses)
        .order_by("scheduled_time")
        .select_related("patient", "doctor__user")
    )
    pend_qs = _filter_appointments_for_user(pend_qs, request.user)
    pend = list(pend_qs[:20])

    current = nxt = None

    def _wait_minutes(appt: Appointment) -> int:
        st = _to_local_aware(appt.scheduled_time)
        if not st:
            return 0
        return max(0, int((now - st).total_seconds() // 60))

    current_obj = None
    if hasattr(AppointmentStatus, "CALLED"):
        for a in pend:
            if a.status == getattr(AppointmentStatus, "CALLED"):
                current_obj = a
                break
    if current_obj is None and pend:
        current_obj = pend[0]

    if current_obj:
        current = {
            "id": current_obj.id,
            "number": current_obj.queue_number,
            "patient_name": current_obj.patient.full_name,
            "doctor_name": _doctor_name(current_obj.doctor),
            "wait_time_minutes": _wait_minutes(current_obj),
            "status": str(current_obj.status),
        }

    # ✅ next = first WAITING appointment that is not the current one
    for a in pend:
        if current_obj and a.id == current_obj.id:
            continue
        if a.status in waiting_statuses:
            nxt = {
                "id": a.id,
                "number": a.queue_number,
                "patient_name": a.patient.full_name,
                "doctor_name": _doctor_name(a.doctor),
                "wait_time_minutes": _wait_minutes(a),
                "status": str(a.status),
            }
            break

    return _json_success({"current_patient": current, "next_patient": nxt})


# ------------------------------------------------------------------#
#                   Secretary Settings & Polling                     #
# ------------------------------------------------------------------#
@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_settings(request: HttpRequest):
    """
    Two separate forms on one page:
      - ProfileUpdateForm  -> form_type=profile
      - CustomPasswordForm -> form_type=password
    We bind/validate ONLY the submitted form to avoid false errors.
    """
    user = request.user

    if request.method == "POST":
        form_type = (request.POST.get("form_type") or "").strip().lower()

        if form_type == "profile":
            profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
            password_form = CustomPasswordForm(user=user)  # unbound
            if profile_form.is_valid():
                changed = profile_form.changed_data
                profile_form.save()
                messages.success(
                    request,
                    (f"✅ تم تحديث الملف الشخصي ({', '.join(changed)}) بنجاح." if changed else "ℹ لم يتم رصد أي تغييرات."),
                )
                return redirect("appointments:secretary_settings")
            messages.error(request, "⚠️ لم يتم حفظ التعديلات. يرجى تصحيح الأخطاء في نموذج الملف الشخصي.")

        elif form_type == "password":
            profile_form = ProfileUpdateForm(instance=user)  # unbound
            password_form = CustomPasswordForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, user)
                if request.POST.get("enforce_logout"):
                    _logout_other_sessions(request)
                messages.success(
                    request,
                    "🔒 تم تغيير كلمة المرور بنجاح. شكرًا لحرصك على أمان حسابك في نظام ClinicHub.",
                )
                return redirect("appointments:secretary_settings")
            messages.error(request, "⚠️ لم يتم تغيير كلمة المرور. يرجى التحقق من البيانات المدخلة.")
        else:
            messages.error(request, "⚠️ تم إرسال نموذج غير معروف. يرجى إعادة تحميل الصفحة وإعادة المحاولة.")
            profile_form = ProfileUpdateForm(instance=user)
            password_form = CustomPasswordForm(user=user)
    else:
        profile_form = ProfileUpdateForm(instance=user)
        password_form = CustomPasswordForm(user=user)

    return render(
        request,
        "appointments/secretary_settings.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


# ------------------------------------------------------------------#
#                         Notification Center                       #
# ------------------------------------------------------------------#
def _notification_queryset_for_user(user):
    queryset = Notification.objects.all()

    if _model_has_field(Notification, "recipient"):
        queryset = queryset.select_related("recipient")

    if _notif_has_related_request():
        queryset = queryset.select_related(
            "related_booking_request",
            "related_booking_request__doctor__user",
        )

    queryset = _filter_notifications_for_user(queryset, user)

    order_field = (
        "-created_at"
        if _model_has_field(Notification, "created_at")
        else "-pk"
    )

    return queryset.order_by(order_field)


def _notification_fallback_url(user) -> str:
    role = getattr(user, "role", "")

    candidates = []

    if getattr(user, "is_superuser", False) or role == "admin":
        candidates.append("admin:index")
    elif role == "doctor":
        candidates.append("doctor:dashboard")
    elif role == "secretary":
        candidates.append("appointments:secretary_dashboard")
    elif role == "patient":
        candidates.append("patient:dashboard")
    elif role in {"lab", "laboratory", "lab_tech", "lab_staff"}:
        candidates.append("lab:dashboard")
    elif role == "pharmacist":
        candidates.append("pharmacy:dashboard")

    candidates.append("home:index")

    for view_name in candidates:
        try:
            return reverse(view_name)
        except Exception:
            continue

    return "/"


def _notification_open_url(notification: Notification) -> str:
    try:
        return reverse(
            "appointments:notification_open",
            kwargs={"pk": notification.pk},
        )
    except Exception:
        return ""


def _serialize_notification(notification: Notification) -> dict[str, Any]:
    created_at = getattr(notification, "created_at", None)

    if created_at:
        try:
            created_at = localtime(created_at)
        except Exception:
            pass

    notification_type = getattr(
        notification,
        "notification_type",
        "system",
    )

    try:
        type_display = notification.get_notification_type_display()
    except Exception:
        type_display = str(notification_type).replace("_", " ").title()

    return {
        "id": notification.pk,
        "title": notification.title,
        "message": notification.message,
        "notification_type": notification_type,
        "notification_type_display": type_display,
        "is_read": notification.is_read,
        "created_at": created_at.isoformat() if created_at else "",
        "open_url": _notification_open_url(notification),
    }


@login_required
@require_GET
def notifications_list(request: HttpRequest):
    queryset = _notification_queryset_for_user(request.user)
    unread_count = queryset.filter(is_read=False).count()
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "appointments/notifications_list.html",
        {
            "notifications": page,
            "unread_count": unread_count,
        },
    )


@login_required
@require_GET
def notifications_api(request: HttpRequest):
    queryset = _notification_queryset_for_user(request.user)
    unread_count = queryset.filter(is_read=False).count()
    recent_notifications = queryset[:10]

    return _json_success(
        {
            "unread_count": unread_count,
            "notifications": [
                _serialize_notification(notification)
                for notification in recent_notifications
            ],
        }
    )


@login_required
@require_GET
def notification_open(request: HttpRequest, pk: int):
    notification = get_object_or_404(
        _notification_queryset_for_user(request.user),
        pk=pk,
    )

    notification.mark_as_read()

    action_url = (
        getattr(notification, "action_url", "")
        or ""
    ).strip()

    if action_url.startswith("/") and not action_url.startswith("//"):
        return redirect(action_url)

    return redirect(_notification_fallback_url(request.user))


@login_required
@require_POST
def notification_mark_read(request: HttpRequest, pk: int):
    notification = get_object_or_404(
        _notification_queryset_for_user(request.user),
        pk=pk,
    )

    notification.mark_as_read()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        unread_count = _notification_queryset_for_user(
            request.user
        ).filter(is_read=False).count()

        return _json_success(
            {
                "notification_id": notification.pk,
                "unread_count": unread_count,
            }
        )

    return redirect("appointments:notifications_list")


@login_required
@require_POST
def notifications_mark_all_read(request: HttpRequest):
    updated_count = _notification_queryset_for_user(
        request.user
    ).filter(is_read=False).update(is_read=True)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return _json_success(
            {
                "updated_count": updated_count,
                "unread_count": 0,
            }
        )

    if updated_count:
        messages.success(request, "All notifications were marked as read.")

    return redirect("appointments:notifications_list")


@secretary_required
@permission_required(
    "appointments.view_patientbookingrequest",
    raise_exception=True,
)
@require_GET
def new_booking_requests_api(request: HttpRequest):
    notifications = Notification.objects.filter(
        is_read=False
    )

    if _notif_has_related_request():
        notifications = notifications.exclude(
            related_booking_request__isnull=True
        )
        notifications = _filter_notifications_for_user(
            notifications,
            request.user,
        )
        notifications = notifications.select_related(
            "related_booking_request__doctor__user",
            "related_booking_request__hospital",
            "related_booking_request__branch",
            "related_booking_request__department",
        )
    else:
        notifications = notifications.none()

    order_field = (
        "-created_at"
        if _model_has_field(Notification, "created_at")
        else "-id"
    )
    notifications = notifications.order_by(order_field)[:50]

    items: list[dict] = []

    for notification in notifications:
        booking_request = getattr(
            notification,
            "related_booking_request",
            None,
        )

        full_name = (
            getattr(booking_request, "full_name", "")
            if booking_request
            else ""
        )
        doctor_object = (
            getattr(booking_request, "doctor", None)
            if booking_request
            else None
        )
        doctor_name = (
            _doctor_name(doctor_object)
            if doctor_object
            else ""
        )
        scheduled_time = (
            _to_local_aware(
                getattr(
                    booking_request,
                    "scheduled_time",
                    None,
                )
            )
            if booking_request
            else None
        )
        time_display = (
            localtime(scheduled_time).strftime(
                "%Y-%m-%d %H:%M"
            )
            if scheduled_time
            else ""
        )
        status = (
            getattr(booking_request, "status", "")
            if booking_request
            else ""
        )
        booking_id = (
            getattr(booking_request, "id", None)
            if booking_request
            else None
        )
        created_at_value = getattr(
            notification,
            "created_at",
            None,
        )
        created_at_string = (
            created_at_value.isoformat()
            if created_at_value
            else ""
        )

        items.append(
            {
                "id": booking_id or notification.id,
                "full_name": full_name,
                "requested_doctor": doctor_name,
                "requested_time_display": time_display,
                "status": status,
                "hospital": (
                    getattr(
                        getattr(
                            booking_request,
                            "hospital",
                            None,
                        ),
                        "name",
                        "",
                    )
                    if booking_request
                    else ""
                ),
                "branch": (
                    getattr(
                        getattr(
                            booking_request,
                            "branch",
                            None,
                        ),
                        "name",
                        "",
                    )
                    if booking_request
                    else ""
                ),
                "department": (
                    getattr(
                        getattr(
                            booking_request,
                            "department",
                            None,
                        ),
                        "name",
                        "",
                    )
                    if booking_request
                    else ""
                ),
                "title": getattr(
                    notification,
                    "title",
                    "",
                ),
                "message": getattr(
                    notification,
                    "message",
                    "",
                ),
                "created_at": created_at_string,
                "source": "notification",
            }
        )

    return _json_success(
        {
            "count": len(items),
            "booking_requests": items,
        }
    )