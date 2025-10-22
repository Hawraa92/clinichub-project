# home/views.py

from django.shortcuts import render
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.http import Http404

from doctor.models import Doctor
from appointments.models import Appointment
from patient.models import Patient
from prescription.models import Prescription


def home_view(request):
    context = {}

    # -------------------------
    # 1) مريض مسجّل → أظهر الأطباء
    # -------------------------
    if request.user.is_authenticated and getattr(request.user, "role", "").lower() == "patient":
        doctors = (
            Doctor.objects
            .select_related("user")
            .filter(user__is_active=True)
            .order_by("user__first_name", "user__last_name")
        )
        context["doctors"] = doctors

    # -------------------------
    # 2) طبيب مسجّل → معلومات اليوم
    # -------------------------
    if request.user.is_authenticated and getattr(request.user, "role", None) == "doctor":
        today = timezone.localdate()

        # مواعيد اليوم
        todays_appointments = (
            Appointment.objects
            .select_related("patient", "doctor__user")
            .filter(
                doctor__user=request.user,
                scheduled_time__date=today
            )
            .order_by("scheduled_time")
        )
        next_queue_number = (
            todays_appointments.first().queue_number
            if todays_appointments else None
        )

        # آخر 5 مرضى تم إنشاؤهم اليوم
        recent_patients = (
            Patient.objects
            .filter(created_at__date=today)
            .order_by("-created_at")[:5]
        )

        # الوصفات المسودّة (status='draft') مرتبة حسب date_issued
        drafted_prescriptions = (
            Prescription.objects
            .select_related("doctor__user", "patient")
            .filter(
                doctor__user=request.user,
                status="draft"
            )
            .order_by("-date_issued")
        )

        context.update({
            "todays_appointments": todays_appointments,
            "next_queue_number": next_queue_number,
            "recent_patients": recent_patients,
            "drafted_prescriptions": drafted_prescriptions,
        })

    # -------------------------
    # 3) الزائر أو السكرتير → الواجهة العادية
    # -------------------------
    return render(request, "home/home.html", context)
