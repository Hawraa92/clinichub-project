from __future__ import annotations

import base64
import io
import json
from datetime import timedelta
from functools import wraps

import qrcode
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import (
    HttpRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timezone import get_default_timezone, localtime, make_aware
from django.views.decorators.cache import cache_control
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)

from accounts.forms import CustomPasswordForm, ProfileUpdateForm
from doctor.models import Doctor
from patient.forms import SecretaryPatientForm
from patient.models import Patient

from .forms import AppointmentForm
from .models import Appointment, AppointmentStatus, PatientBookingRequest

# Optional BookingRequestStatus for lighter builds
try:  # pragma: no cover
    from .models import BookingRequestStatus  # type: ignore
except Exception:  # pragma: no cover
    BookingRequestStatus = None  # type: ignore


# ------------------------------------------------------------------#
#                           Helpers                                  #
# ------------------------------------------------------------------#
_LOCAL_TZ = get_default_timezone()


def _json_success(data) -> JsonResponse:
    return JsonResponse({"success": True, **data})


def _json_error(msg: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": msg}, status=status)


def _today():
    return timezone.localdate()


def _doctor_name(doc: Doctor) -> str:
    return (
        getattr(doc, "get_display_name", lambda: "")()
        or getattr(doc, "full_name", "")
        or doc.user.get_full_name()
        or doc.user.first_name
        or (doc.user.username.split("@")[0] if "@" in doc.user.username else doc.user.username)
        or "Doctor"
    )


def _user_name(u) -> str:
    return (
        u.get_full_name()
        or u.first_name
        or (u.username.split("@")[0] if "@" in u.username else u.username)
        or "User"
    )


def _to_local_aware(dt):
    """Normalize naive datetimes to local TZ without changing the wall clock."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return make_aware(dt, _LOCAL_TZ)
    return dt.astimezone(_LOCAL_TZ)


def _model_has_field(model, field_name: str) -> bool:
    try:
        return any(getattr(f, "name", "") == field_name for f in model._meta.get_fields())  # type: ignore[attr-defined]
    except Exception:
        return False


def secretary_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *a, **kw):
        if getattr(request.user, "role", None) != "secretary" and not request.user.is_superuser:
            return HttpResponseForbidden("You do not have permission to access this page.")
        return view(request, *a, **kw)

    return wrapper


def is_patient(user) -> bool:
    return getattr(user, "role", None) == "patient"


def _logout_other_sessions(request: HttpRequest) -> None:
    """Log out all other sessions except the current one."""
    Session.objects.filter(expire_date__gte=timezone.now()).exclude(
        session_key=request.session.session_key
    ).delete()


# ------------------------------------------------------------------#
#                     Secretary Dashboard                           #
# ------------------------------------------------------------------#
@secretary_required
@require_GET
def secretary_dashboard(request: HttpRequest):
    today = _today()
    base = Appointment.objects.select_related("patient", "doctor__user")

    todays = base.filter(scheduled_time__date=today)

    # revenue_today_iqd is optional → compute only if the field exists
    revenue_today = 0
    if _model_has_field(Appointment, "iqd_amount"):
        revenue_today = todays.aggregate(total=Sum("iqd_amount")).get("total") or 0

    stats = {
        "patients_today": base.filter(scheduled_time__date=today)
        .values("patient_id")
        .distinct()
        .count(),
        "new_patients_today": Patient.objects.filter(created_at__date=today).count()
        if _model_has_field(Patient, "created_at")
        else 0,
        "total_patients": Patient.objects.count(),
        "appointments_today": todays.count(),
        "revenue_today_iqd": revenue_today,
    }

    week_start = today - timedelta(days=today.weekday())
    rows = (
        base.filter(scheduled_time__date__range=[week_start, week_start + timedelta(days=6)])
        .annotate(day=TruncDate("scheduled_time"))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts = {r["day"]: r["count"] for r in rows}
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    chart = [counts.get(week_start + timedelta(days=i), 0) for i in range(7)]

    ctx = {
        "appointment_form": AppointmentForm(),
        "patient_form": SecretaryPatientForm(),
        "appointments": base.order_by("-scheduled_time")[:20],
        "today_appointments": todays,
        "stats": stats,
        "chart_data_json": json.dumps({"labels": labels, "data": chart}),
    }
    return render(request, "appointments/secretary_dashboard.html", ctx)


# ------------------------------------------------------------------#
#                        Appointment CRUD                           #
# ------------------------------------------------------------------#
@secretary_required
@require_http_methods(["GET", "POST"])
def create_appointment(request: HttpRequest):
    """
    Secretary-created appointments:
    - Rely on models.Appointment.save() to atomically assign queue_number.
    - Do NOT compute queue_number here to avoid race conditions.
    """
    form = AppointmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        appt: Appointment = form.save(commit=False)
        appt.scheduled_time = _to_local_aware(appt.scheduled_time)
        try:
            appt.save()  # queue_number is assigned atomically in models.save()
        except IntegrityError:
            messages.error(request, "❌ This time slot is already booked for this doctor.")
            return render(request, "appointments/create_appointment.html", {"form": form})
        messages.success(
            request,
            f"✅ Appointment booked for {appt.patient.full_name} "
            f"with Dr. {_doctor_name(appt.doctor)} "
            f"at {localtime(appt.scheduled_time):%I:%M %p}.",
        )
        return redirect("appointments:appointment_ticket", pk=appt.pk)
    elif request.method == "POST":
        messages.error(request, "❌ Please correct the errors below.")
    return render(request, "appointments/create_appointment.html", {"form": form})


@secretary_required
@require_GET
def appointment_ticket(request: HttpRequest, pk: int):
    appt = get_object_or_404(
        Appointment.objects.select_related("doctor__user", "patient"), pk=pk
    )

    qr = qrcode.make(request.build_absolute_uri(), box_size=6, border=2)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")

    ctx = {
        "appointment": appt,
        "doctor_name": _doctor_name(appt.doctor),
        "doctor_spec": getattr(appt.doctor, "specialty", ""),
        "secretary_name": _user_name(request.user),
        "qr_code": base64.b64encode(buf.getvalue()).decode(),
    }
    return render(request, "appointments/appointment_ticket.html", ctx)


@secretary_required
@require_http_methods(["GET", "POST"])
def edit_appointment(request: HttpRequest, pk: int):
    appt = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appt)
    if request.method == "POST" and form.is_valid():
        appt = form.save(commit=False)
        appt.scheduled_time = _to_local_aware(appt.scheduled_time)
        try:
            appt.save()
        except IntegrityError:
            messages.error(request, "❌ This time slot is already booked for this doctor.")
            return render(
                request,
                "appointments/edit_appointment.html",
                {"form": form, "appointment": appt},
            )
        messages.success(request, "✅ Appointment updated successfully.")
        return redirect("appointments:appointment_list")
    elif request.method == "POST":
        messages.error(request, "❌ Please correct the errors below.")
    return render(
        request,
        "appointments/edit_appointment.html",
        {"form": form, "appointment": appt},
    )


@secretary_required
@require_http_methods(["GET", "POST"])
def cancel_appointment(request: HttpRequest, pk: int):
    """Soft cancel: forbid COMPLETED; set status=CANCELLED."""
    appt = get_object_or_404(Appointment, pk=pk)

    if appt.status == AppointmentStatus.COMPLETED:
        messages.error(request, "❌ Cannot cancel a completed appointment.")
        return redirect("appointments:appointment_list")

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()

        update_kwargs: dict[str, object] = {"status": AppointmentStatus.CANCELLED}

        # Append a note if the model provides a `notes` field
        if reason and _model_has_field(Appointment, "notes"):
            stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            user_display = request.user.get_full_name() or request.user.username
            note_line = f"[Cancelled {stamp} by {user_display}] {reason}"
            new_notes = f"{getattr(appt, 'notes', '')}\n{note_line}".strip()
            update_kwargs["notes"] = new_notes

        Appointment.objects.filter(pk=appt.pk).update(**update_kwargs)

        messages.success(request, "✅ Appointment cancelled successfully.")
        return redirect("appointments:appointment_list")

    return render(request, "appointments/delete_confirmation.html", {"appointment": appt})


@secretary_required
@require_http_methods(["GET", "POST"])
def delete_appointment(request: HttpRequest, pk: int):
    """Hard delete — admins only."""
    appt = get_object_or_404(Appointment, pk=pk)
    if not request.user.is_superuser:
        messages.error(
            request, "❌ Only administrators can delete appointments permanently."
        )
        return redirect("appointments:appointment_list")

    if request.method == "POST":
        appt.delete()
        messages.success(request, "🗑️ Appointment deleted permanently.")
        return redirect("appointments:appointment_list")
    return render(request, "appointments/delete_confirmation.html", {"appointment": appt})


@secretary_required
@require_GET
def appointment_list(request: HttpRequest):
    sort = request.GET.get("sort", "scheduled_time")
    fld = {
        "patient": "patient__full_name",
        "doctor": "doctor__user__first_name",
        "scheduled_time": "scheduled_time",
    }.get(sort, "scheduled_time")

    qs = Appointment.objects.select_related("patient", "doctor__user")

    # Status filter: only the three canonical states
    status_key = (request.GET.get("status") or "all").lower()
    status_map = {
        "pending": AppointmentStatus.PENDING,
        "completed": AppointmentStatus.COMPLETED,
        "cancelled": AppointmentStatus.CANCELLED,
    }
    if status_key in status_map:
        qs = qs.filter(status=status_map[status_key])

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(patient__full_name__icontains=q)
            | Q(doctor__user__first_name__icontains=q)
            | Q(doctor__user__last_name__icontains=q)
            | Q(notes__icontains=q) if _model_has_field(Appointment, "notes") else Q()
        )

    page = Paginator(qs.order_by(f"-{fld}"), 10).get_page(request.GET.get("page"))
    return render(
        request,
        "appointments/appointment_list.html",
        {
            "appointments": page,
            "search_query": q,
            "current_sort": sort,
            "current_status": status_key,
        },
    )


# ------------------------------------------------------------------#
#                Patient Portal Booking (IN-APP)                    #
# ------------------------------------------------------------------#
class _PatientPortalBookingForm(forms.ModelForm):
    """Minimal form for logged-in patients: choose time only."""

    class Meta:
        model = Appointment
        fields = ["scheduled_time"]
        widgets = {
            "scheduled_time": forms.DateTimeInput(attrs={"type": "datetime-local"})
        }

    def __init__(self, *args, doctor: Doctor | None = None, **kwargs):
        self.doctor = doctor
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("scheduled_time")
        if st and st <= timezone.now():
            self.add_error("scheduled_time", "Please choose a future time.")
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
    patient = get_object_or_404(Patient, user=request.user)

    if request.method == "POST":
        form = _PatientPortalBookingForm(request.POST, doctor=doctor)
        if form.is_valid():
            sched = _to_local_aware(form.cleaned_data["scheduled_time"])

            if BookingRequestStatus:
                # Create a booking request (does NOT block the slot yet)
                full_name = (
                    patient.full_name
                    or request.user.get_full_name()
                    or request.user.username
                )
                contact = (
                    getattr(patient, "phone", "")
                    or getattr(patient, "mobile", "")
                    or request.user.email
                    or ""
                )
                dob = getattr(patient, "date_of_birth", None)

                br_kwargs: dict[str, object] = dict(
                    doctor=doctor,
                    full_name=full_name,
                    contact_info=contact,
                    date_of_birth=dob,
                    scheduled_time=sched,
                    status=getattr(BookingRequestStatus, "PENDING", None)
                    or getattr(BookingRequestStatus, "REQUESTED", None),
                )
                # Attach patient/user if model supports these fields
                if _model_has_field(PatientBookingRequest, "patient"):
                    br_kwargs["patient"] = patient
                if _model_has_field(PatientBookingRequest, "user"):
                    br_kwargs["user"] = request.user

                PatientBookingRequest.objects.create(**br_kwargs)

                # Notify secretaries (best-effort)
                try:
                    from notifications.models import Notification  # type: ignore

                    Notification.objects.create(
                        to_role="secretary" if hasattr(Notification, "to_role") else None,
                        title="New booking request",
                        message=(
                            f"{full_name} requested {_doctor_name(doctor)} at "
                            f"{localtime(sched):%Y-%m-%d %H:%M}"
                        ),
                        link="/appointments/secretary/",  # dashboard bell
                    )
                except Exception:
                    pass

                messages.success(
                    request, "Your request was sent and is pending secretary approval."
                )
                # No actual appointment yet
                return redirect("patient:dashboard")

            else:
                # Fallback: create a real Appointment as PENDING (queue_number assigned by model)
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
                    messages.error(
                        request, "❌ This time slot is already booked for this doctor."
                    )
                    return redirect("appointments:my_appointments")

                try:
                    from notifications.models import Notification  # type: ignore

                    Notification.objects.create(
                        to_role="secretary" if hasattr(Notification, "to_role") else None,
                        title="New appointment request",
                        message=(
                            f"{patient.full_name} requested {_doctor_name(doctor)} at "
                            f"{localtime(sched):%Y-%m-%d %H:%M}"
                        ),
                        link="/appointments/secretary/appointments/?status=pending",
                    )
                except Exception:
                    pass
                messages.success(request, "Your request was sent and is pending approval.")
                return redirect("appointments:my_appointments")
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

    patient = get_object_or_404(Patient, user=request.user)

    # Actual appointments
    appointments = (
        Appointment.objects.filter(patient=patient)
        .select_related("doctor", "doctor__user")
        .order_by("-scheduled_time")
    )

    # Pending booking requests (best-effort match)
    booking_requests: list[PatientBookingRequest] = []
    if BookingRequestStatus:
        q = PatientBookingRequest.objects.all()

        # Filter by status if enum exists
        if hasattr(BookingRequestStatus, "PENDING"):
            q = q.filter(status=BookingRequestStatus.PENDING)
        elif hasattr(BookingRequestStatus, "REQUESTED"):
            q = q.filter(status=BookingRequestStatus.REQUESTED)

        if _model_has_field(PatientBookingRequest, "patient"):
            q = q.filter(patient=patient)
        elif _model_has_field(PatientBookingRequest, "user"):
            q = q.filter(user=request.user)
        else:
            # Heuristic match by contact/name/email/phone
            lookups = Q()
            phone = getattr(patient, "phone", None) or getattr(patient, "mobile", None)
            if phone:
                lookups |= Q(contact_info__icontains=phone)
            if request.user.email:
                lookups |= Q(contact_info__icontains=request.user.email)
            display_name = (
                patient.full_name or request.user.get_full_name() or request.user.username
            )
            if display_name:
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


# Keep backward-compat route name by providing approve_appointment that delegates
@secretary_required
@require_POST
def approve_appointment(request: HttpRequest, pk: int):
    return confirm_appointment(request, pk)


@secretary_required
@require_POST
def confirm_appointment(request: HttpRequest, pk: int):
    """
    Confirm an Appointment (no APPROVED state in enum):
    - If it's cancelled, refuse.
    - Otherwise, keep/force to PENDING to indicate it's accepted.
    """
    appt = get_object_or_404(Appointment, pk=pk)
    if appt.status == AppointmentStatus.CANCELLED:
        messages.error(request, "❌ Cannot confirm a cancelled appointment.")
    else:
        appt.status = AppointmentStatus.PENDING
        appt.save(update_fields=["status"])
        messages.success(request, "Appointment confirmed.")
    return redirect("appointments:appointment_list")


# Optional: approve a booking request and convert it into an Appointment
@secretary_required
@require_POST
def approve_booking_request(request: HttpRequest, pk: int):
    """Convert a PatientBookingRequest -> Appointment and mark request as confirmed."""
    if not BookingRequestStatus:
        return _json_error("Booking requests are not enabled.", status=400)

    br = get_object_or_404(PatientBookingRequest, pk=pk)

    # Find patient
    patient_obj: Patient | None = None
    if _model_has_field(PatientBookingRequest, "patient") and getattr(br, "patient", None):
        patient_obj = br.patient  # type: ignore[attr-defined]
    elif _model_has_field(PatientBookingRequest, "user") and getattr(br, "user", None):
        patient_obj = Patient.objects.filter(user=br.user).first()  # type: ignore[attr-defined]

    if not patient_obj:
        # Fallback heuristic by name/email/phone
        qs = Patient.objects.all()
        if getattr(br, "contact_info", None):
            qs = qs.filter(
                Q(phone__icontains=br.contact_info)
                | Q(mobile__icontains=br.contact_info)
                | Q(user__email__iexact=br.contact_info)
            )
        if not qs.exists() and getattr(br, "full_name", None):
            qs = Patient.objects.filter(full_name__icontains=br.full_name)
        patient_obj = qs.first()

    if not patient_obj:
        messages.error(
            request,
            "Cannot approve: patient record not linked/found. Please convert manually.",
        )
        return redirect("appointments:secretary_dashboard")

    with transaction.atomic():
        Appointment.objects.create(
            patient=patient_obj,
            doctor=br.doctor,
            scheduled_time=_to_local_aware(getattr(br, "scheduled_time", None)),
            status=AppointmentStatus.PENDING,
        )
        # Mark request CONFIRMED/APPROVED if exists
        try:
            if hasattr(BookingRequestStatus, "CONFIRMED"):
                br.status = BookingRequestStatus.CONFIRMED
            elif hasattr(BookingRequestStatus, "APPROVED"):
                br.status = BookingRequestStatus.APPROVED
            else:
                br.status = getattr(BookingRequestStatus, "PENDING", None)
            br.save(update_fields=["status"])
        except Exception:
            pass

    messages.success(request, "Booking request approved and appointment created.")
    return redirect("appointments:appointment_list")


# ------------------------------------------------------------------#
#                  Public vs Internal Queue Snapshots               #
# ------------------------------------------------------------------#

def _queue_snapshot_internal() -> list[dict]:
    """
    INTERNAL snapshot (PHI included) – for authenticated secretary endpoints/APIs.
    """
    today = _today()
    default_mins = getattr(settings, "APPOINTMENT_DURATION_MINUTES", 15)

    appts = (
        Appointment.objects.filter(
            scheduled_time__date=today, status=AppointmentStatus.PENDING
        )
        .select_related("patient", "doctor__user")
        .order_by("scheduled_time")
    )

    doctor_ids = sorted({a.doctor_id for a in appts})
    doctors = (
        Doctor.objects.select_related("user").filter(id__in=doctor_ids).order_by("id")
    )

    by_doc: dict[int, list[Appointment]] = {}
    for a in appts:
        by_doc.setdefault(a.doctor_id, []).append(a)

    queues: list[dict] = []
    for d in doctors:
        today_appts = by_doc.get(d.id, [])
        current, waiting = None, []
        if today_appts:
            first, rest = today_appts[0], today_appts[1:]
            current = {
                "id": first.id,
                "number": f"P-{first.queue_number:03d}" if first.queue_number else "-",
                "patient_name": first.patient.full_name,
                "time": first.scheduled_time.strftime("%H:%M"),
            }
            waiting = [
                {
                    "id": w.id,
                    "number": f"P-{w.queue_number:03d}" if w.queue_number else "-",
                    "patient_name": w.patient.full_name,
                    "time": w.scheduled_time.strftime("%H:%M"),
                }
                for w in rest
            ]
        queues.append(
            {
                "doctor_id": d.id,
                "doctor_name": _doctor_name(d),
                "status": "available" if today_appts else "on_break",
                "current_patient": current,
                "waiting_list": waiting,
                "avg_time": default_mins,
            }
        )
    return queues


def _queue_snapshot_public() -> list[dict]:
    """
    PUBLIC snapshot (PHI-FREE) – no patient names/details.
    """
    today = _today()
    default_mins = getattr(settings, "APPOINTMENT_DURATION_MINUTES", 15)

    appts = (
        Appointment.objects.filter(
            scheduled_time__date=today, status=AppointmentStatus.PENDING
        )
        .select_related("doctor__user")
        .order_by("scheduled_time")
    )

    doctor_ids = sorted({a.doctor_id for a in appts})
    doctors = (
        Doctor.objects.select_related("user").filter(id__in=doctor_ids).order_by("id")
    )

    by_doc: dict[int, list[Appointment]] = {}
    for a in appts:
        by_doc.setdefault(a.doctor_id, []).append(a)

    queues: list[dict] = []
    for d in doctors:
        today_appts = by_doc.get(d.id, [])
        current, waiting = None, []
        if today_appts:
            first, rest = today_appts[0], today_appts[1:]
            current = {
                "id": first.id,
                "number": f"P-{first.queue_number:03d}" if first.queue_number else "-",
                "time": first.scheduled_time.strftime("%H:%M"),
            }
            waiting = [
                {
                    "id": w.id,
                    "number": f"P-{w.queue_number:03d}" if w.queue_number else "-",
                    "time": w.scheduled_time.strftime("%H:%M"),
                }
                for w in rest
            ]
        queues.append(
            {
                "doctor_id": d.id,
                "doctor_name": _doctor_name(d),
                "status": "available" if today_appts else "on_break",
                "current": current,
                "waiting": waiting,
                "avg_time": default_mins,
            }
        )
    return queues


@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def queue_display(request: HttpRequest):
    # PUBLIC view → PHI-free (template may still fetch JSON API)
    return render(request, "appointments/queue_display.html", {"queues": _queue_snapshot_public()})


@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def queue_public_api(request: HttpRequest):
    # PUBLIC JSON API → PHI-FREE
    return _json_success({"queues": _queue_snapshot_public()})


@secretary_required
@require_GET
def queue_number_api(request: HttpRequest):
    # INTERNAL API for secretaries/admins → PHI allowed
    return _json_success({"queues": _queue_snapshot_internal()})


@secretary_required
@require_POST
def call_next_api(request: HttpRequest, doctor_id: int):
    """
    Mark next (or specific) PENDING appointment as COMPLETED for this doctor.
    Uses .save() to trigger signals; returns updated queues + updated appt info.
    """
    today = _today()
    appt_id = request.POST.get("appointment_id")

    with transaction.atomic():
        base_qs = (
            Appointment.objects.select_for_update()
            .filter(
                doctor_id=doctor_id,
                status=AppointmentStatus.PENDING,
                scheduled_time__date=today,
            )
            .order_by("scheduled_time")
        )

        nxt = None
        if appt_id:
            nxt = (
                Appointment.objects.select_for_update()
                .filter(pk=appt_id, doctor_id=doctor_id)
                .first()
            )
            if (
                not nxt
                or nxt.status != AppointmentStatus.PENDING
                or (nxt.scheduled_time and nxt.scheduled_time.date() != today)
            ):
                nxt = base_qs.first()
        else:
            nxt = base_qs.first()

        if not nxt:
            return _json_error("No pending appointments.", status=404)

        nxt.status = AppointmentStatus.COMPLETED
        nxt.save(update_fields=["status"])  # trigger signals if any

    return _json_success(
        {
            "updated": {
                "id": nxt.pk,
                "status": nxt.status,
                "patient": getattr(nxt.patient, "full_name", ""),
                "time": localtime(nxt.scheduled_time).strftime("%H:%M")
                if nxt.scheduled_time
                else "",
            },
            "queues": _queue_snapshot_internal(),
        }
    )


@secretary_required
@require_GET
def current_patient_api(request: HttpRequest):
    today = _today()
    now = timezone.now()

    pend = list(
        Appointment.objects.filter(
            scheduled_time__date=today, status=AppointmentStatus.PENDING
        )
        .order_by("scheduled_time")
        .select_related("patient", "doctor__user")
    )

    current = nxt = None
    if pend:
        p0 = pend[0]
        current = {
            "id": p0.id,
            "number": p0.queue_number,
            "patient_name": p0.patient.full_name,
            "doctor_name": _doctor_name(p0.doctor),
            "wait_time_minutes": max(
                0, int((now - p0.scheduled_time).total_seconds() // 60)
            ),
        }
    if len(pend) > 1:
        p1 = pend[1]
        nxt = {
            "id": p1.id,
            "number": p1.queue_number,
            "patient_name": p1.patient.full_name,
            "doctor_name": _doctor_name(p1.doctor),
            "wait_time_minutes": max(
                0, int((now - p1.scheduled_time).total_seconds() // 60)
            ),
        }
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
            profile_form = ProfileUpdateForm(
                request.POST, request.FILES, instance=user
            )
            password_form = CustomPasswordForm(user=user)  # unbound
            if profile_form.is_valid():
                changed = profile_form.changed_data
                profile_form.save()
                messages.success(
                    request,
                    f"✅ Profile updated ({', '.join(changed)})!"
                    if changed
                    else "ℹ No changes detected.",
                )
                return redirect("appointments:secretary_settings")
            messages.error(request, "❌ Please fix the profile errors.")
        elif form_type == "password":
            profile_form = ProfileUpdateForm(instance=user)  # unbound
            password_form = CustomPasswordForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, user)
                if request.POST.get("enforce_logout"):
                    _logout_other_sessions(request)
                messages.success(request, "🔒 Password changed successfully.")
                return redirect("appointments:secretary_settings")
            messages.error(request, "❌ Please fix the password errors.")
        else:
            # Fallback: treat as GET if form_type missing/unknown
            messages.error(request, "Unknown form submitted.")
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


@secretary_required
@require_GET
def new_booking_requests_api(request: HttpRequest):
    """
    Bell counter API:
    - If a Notification model exists → count UNREAD notifications to secretaries only.
    - Else → count ONLY pending booking requests (NOT pending appointments).
    This decouples the bell from Next Call / queue status.
    """
    items: list[dict] = []

    # 1) Prefer dedicated Notification model if available
    try:
        from notifications.models import Notification as NotiModel  # type: ignore

        q = NotiModel.objects.all()
        # filter to secretary role if field exists
        if _model_has_field(NotiModel, "to_role"):
            q = q.filter(to_role="secretary")
        elif _model_has_field(NotiModel, "recipient_role"):
            q = q.filter(recipient_role="secretary")

        # unread-only if field exists; otherwise take all (best effort)
        if _model_has_field(NotiModel, "is_read"):
            q = q.filter(is_read=False)
        elif _model_has_field(NotiModel, "read_at"):
            q = q.filter(read_at__isnull=True)

        # order by most recent if possible
        if _model_has_field(NotiModel, "created_at"):
            q = q.order_by("-created_at")
        elif _model_has_field(NotiModel, "created"):
            q = q.order_by("-created")

        count = q.count()
        for n in q[:50]:
            title = getattr(n, "title", "") or getattr(n, "event", "") or "Notification"
            message = getattr(n, "message", "") or getattr(n, "text", "")
            link = getattr(n, "link", "") or getattr(n, "url", "")
            items.append(
                {
                    "id": n.pk,
                    "title": str(title),
                    "message": str(message),
                    "link": str(link),
                    "source": "notification",
                }
            )
        return _json_success({"count": count, "booking_requests": items})
    except Exception:
        # Fall through to booking requests-only
        pass

    # 2) Fallback: ONLY pending booking requests (no appointments)
    if BookingRequestStatus:
        pending_reqs = (
            PatientBookingRequest.objects.filter(
                status=getattr(BookingRequestStatus, "PENDING", None)
                or getattr(BookingRequestStatus, "REQUESTED", None)
            ).select_related("doctor__user")
        )
        if _model_has_field(PatientBookingRequest, "submitted_at"):
            pending_reqs = pending_reqs.order_by("-submitted_at")
        else:
            pending_reqs = pending_reqs.order_by("-scheduled_time")

        for r in pending_reqs[:50]:
            items.append(
                {
                    "id": r.id,
                    "full_name": getattr(r, "full_name", ""),
                    "requested_doctor": _doctor_name(r.doctor),
                    "requested_time_display": localtime(r.scheduled_time).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    if getattr(r, "scheduled_time", None)
                    else "",
                    "status": getattr(r, "status", ""),
                    "source": "request",
                }
            )

    return _json_success({"count": len(items), "booking_requests": items})
