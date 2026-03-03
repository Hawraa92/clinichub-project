# prescription/tests/factories.py
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment

User = get_user_model()


def _uniq_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@x.com"


def _future_dt(minutes: int = 60):
    return timezone.now() + timedelta(minutes=minutes)


def _user_field_names() -> set[str]:
    try:
        return {f.name for f in User._meta.fields}
    except Exception:
        return set()


# -----------------------
# Base creators
# -----------------------
def create_user(
    *,
    email: str | None = None,
    role: str = "patient",
    password: str = "Pass12345!",
    is_superuser: bool = False,
    username: str | None = None,
    **extra_fields,
):
    """
    Robust user creator for your custom user model.
    - supports email as login
    - supports optional username field if present
    - passes role= if supported by your manager
    """
    email = (email or _uniq_email(role)).strip().lower()

    fields = _user_field_names()
    if "username" in fields:
        if not username:
            username = (email.split("@", 1)[0] or f"user_{uuid4().hex[:6]}")[:150]
        extra_fields.setdefault("username", username)

    if is_superuser:
        return User.objects.create_superuser(email=email, password=password, **extra_fields)

    # your custom manager supports role=
    return User.objects.create_user(email=email, password=password, role=role, **extra_fields)


def create_doctor(*, email: str | None = None, user=None, **doctor_fields) -> Doctor:
    if user is None:
        user = create_user(role="doctor", email=email or _uniq_email("doctor"))
    try:
        return Doctor.objects.create(user=user, **doctor_fields)
    except TypeError:
        return Doctor.objects.create(user=user)


def create_patient(
    *,
    full_name: str = "Test Patient",
    email: str | None = None,
    user=None,
    doctor: Doctor | None = None,
    **patient_fields,
) -> Patient:
    if user is None:
        user = create_user(role="patient", email=email or _uniq_email("patient"))

    # Patient model in your project supports full_name + user
    p = Patient.objects.create(full_name=full_name, user=user, **patient_fields)

    # attach doctor only if Patient has such FK
    if doctor is not None:
        try:
            p.doctor = doctor
            p.save(update_fields=["doctor"])
        except Exception:
            pass

    return p


def create_appointment(
    *,
    doctor: Doctor,
    patient: Patient,
    scheduled_time=None,
    status=None,
    minutes_from_now: int = 60,
    **appt_fields,
) -> Appointment:
    st = scheduled_time or _future_dt(minutes_from_now)

    data = {
        "doctor": doctor,
        "patient": patient,
        "scheduled_time": st,
        **appt_fields,
    }
    if status is not None:
        data["status"] = status

    try:
        return Appointment.objects.create(**data)
    except TypeError:
        # if appt_fields contain unknown fields, retry minimal set
        data = {"doctor": doctor, "patient": patient, "scheduled_time": st}
        if status is not None:
            data["status"] = status
        return Appointment.objects.create(**data)


# -----------------------
# REQUIRED by tests: make_* helpers
# -----------------------
def make_user(
    email: str | None = None,
    role: str = "patient",
    *,
    password: str = "Pass12345!",
    is_superuser: bool = False,
    username: str | None = None,
    **kwargs,
):
    """
    Supports BOTH:
      - make_user("sec@x.com", "secretary")
      - make_user(email="sec@x.com", role="secretary")
    """
    return create_user(
        email=email or _uniq_email(role),
        role=role,
        password=password,
        is_superuser=is_superuser,
        username=username,
        **kwargs,
    )


def make_doctor(email: str | None = None, user=None, **kwargs) -> Doctor:
    return create_doctor(email=email, user=user, **kwargs)


def make_patient(
    full_name: str = "Test Patient",
    email: str | None = None,
    doctor: Doctor | None = None,
    user=None,
    **kwargs,
) -> Patient:
    return create_patient(full_name=full_name, email=email, doctor=doctor, user=user, **kwargs)


def make_appointment(
    doctor: Doctor | None = None,
    patient: Patient | None = None,
    *,
    minutes_from_now: int = 60,
    scheduled_time=None,
    status=None,
    **kwargs,
) -> Appointment:
    """
    Supports BOTH:
      - make_appointment(doc, pat)
      - make_appointment(doctor=..., patient=...)
    """
    doctor = doctor or make_doctor()
    patient = patient or make_patient(doctor=doctor)
    return create_appointment(
        doctor=doctor,
        patient=patient,
        minutes_from_now=minutes_from_now,
        scheduled_time=scheduled_time,
        status=status,
        **kwargs,
    )


def make_prescription(
    appointment: Appointment | None = None,  # positional-friendly
    *,
    doctor: Doctor | None = None,
    patient: Patient | None = None,
    **kwargs,
):
    """
    Supports BOTH:
      - make_prescription(appt)
      - make_prescription(appointment=appt)

    Creates Prescription robustly regardless of whether your model uses:
    - appointment FK
    - doctor FK
    - patient FK
    """
    appt = appointment or make_appointment(doctor=doctor, patient=patient)
    doctor = doctor or appt.doctor
    patient = patient or appt.patient

    Prescription = apps.get_model("prescription", "Prescription")
    field_names = {f.name for f in Prescription._meta.fields}

    data = {}
    if "appointment" in field_names:
        data["appointment"] = appt
    if "doctor" in field_names:
        data["doctor"] = doctor
    if "patient" in field_names:
        data["patient"] = patient

    data.update(kwargs)
    return Prescription.objects.create(**data)


__all__ = [
    "create_user",
    "create_doctor",
    "create_patient",
    "create_appointment",
    "make_user",
    "make_doctor",
    "make_patient",
    "make_appointment",
    "make_prescription",
]