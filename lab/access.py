from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from doctor.models import Doctor
from hospital.models import Branch, StaffAssignment
from patient.models import Patient

from .models import LabOrder, LabResult


def is_platform_admin(user: Any) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )


def active_staff_assignments(
    user: Any,
    *,
    role: str | None = None,
) -> QuerySet:
    if not getattr(user, "is_authenticated", False):
        return StaffAssignment.objects.none()

    qs = StaffAssignment.objects.filter(
        user=user,
        is_active=True,
        is_deleted=False,
        hospital__is_active=True,
        hospital__is_deleted=False,
    ).filter(
        Q(branch__isnull=True)
        | Q(
            branch__is_active=True,
            branch__is_deleted=False,
        )
    )

    if role:
        qs = qs.filter(role=role)

    return qs.select_related("hospital", "branch").order_by(
        "-is_primary",
        "hospital_id",
        "branch_id",
        "pk",
    )


def _tenant_scope_q(assignments: QuerySet) -> Q:
    scope = Q(pk__in=[])

    for assignment in assignments:
        if assignment.branch_id:
            scope |= Q(
                hospital_id=assignment.hospital_id,
                branch_id=assignment.branch_id,
            )
        else:
            scope |= Q(hospital_id=assignment.hospital_id)

    return scope


def _doctor_assignment_candidates(doctor: Doctor) -> QuerySet:
    user_id = getattr(doctor, "user_id", None)
    if not user_id:
        return StaffAssignment.objects.none()

    return active_staff_assignments(
        doctor.user,
        role=StaffAssignment.Roles.DOCTOR,
    )


def _filter_assignments_for_tenant(
    assignments: QuerySet,
    *,
    hospital_id: int | None,
    branch_id: int | None,
) -> QuerySet:
    if hospital_id:
        assignments = assignments.filter(hospital_id=hospital_id)
    if branch_id:
        assignments = assignments.filter(branch_id=branch_id)
    return assignments


def resolve_lab_order_tenant_snapshot(
    order: LabOrder,
    *,
    explicit_hospital_id: int | str | None = None,
    explicit_branch_id: int | str | None = None,
) -> tuple[int, int | None]:
    """
    Resolve immutable creation-time LabOrder tenant ownership.

    Appointment-linked orders snapshot the appointment location. Browser
    submitted tenant ids are ignored in that path. Appointmentless orders may
    use an explicit context only after it resolves to exactly one active doctor
    assignment; otherwise they must have exactly one active assignment.
    """
    appointment = getattr(order, "appointment", None)

    if appointment is not None:
        hospital_id = getattr(appointment, "hospital_id", None)
        branch_id = getattr(appointment, "branch_id", None)

        errors = {}
        if not hospital_id:
            errors["hospital"] = "The selected appointment has no hospital."
        if not branch_id:
            errors["branch"] = "The selected appointment has no branch."
        if getattr(appointment, "patient_id", None) != getattr(order, "patient_id", None):
            errors["patient"] = "The selected appointment does not belong to this patient."
        if getattr(appointment, "doctor_id", None) != getattr(order, "doctor_id", None):
            errors["doctor"] = "The selected appointment does not belong to this doctor."

        if branch_id:
            branch_hospital_id = (
                Branch.objects.filter(pk=branch_id)
                .values_list("hospital_id", flat=True)
                .first()
            )
            if branch_hospital_id != hospital_id:
                errors["branch"] = "The selected appointment branch does not belong to its hospital."

        if errors:
            raise ValidationError(errors)

        if not _filter_assignments_for_tenant(
            _doctor_assignment_candidates(order.doctor),
            hospital_id=hospital_id,
            branch_id=branch_id,
        ).exists():
            raise ValidationError(
                {
                    "doctor": (
                        "This doctor does not have an active assignment "
                        "for the selected appointment tenant."
                    )
                }
            )

        return hospital_id, branch_id

    assignments = _doctor_assignment_candidates(order.doctor)

    try:
        hospital_id = int(explicit_hospital_id) if explicit_hospital_id else None
    except (TypeError, ValueError):
        raise ValidationError({"hospital": "Invalid hospital context."})

    try:
        branch_id = int(explicit_branch_id) if explicit_branch_id else None
    except (TypeError, ValueError):
        raise ValidationError({"branch": "Invalid branch context."})

    if branch_id and not hospital_id:
        hospital_id = (
            Branch.objects.filter(pk=branch_id)
            .values_list("hospital_id", flat=True)
            .first()
        )
        if not hospital_id:
            raise ValidationError({"branch": "Invalid branch context."})

    if hospital_id and branch_id:
        branch_hospital_id = (
            Branch.objects.filter(pk=branch_id)
            .values_list("hospital_id", flat=True)
            .first()
        )
        if branch_hospital_id != hospital_id:
            raise ValidationError({"branch": "The selected branch does not belong to this hospital."})

    assignments = _filter_assignments_for_tenant(
        assignments,
        hospital_id=hospital_id,
        branch_id=branch_id,
    )

    assignment_count = assignments.count()
    if assignment_count == 0:
        raise ValidationError(
            {"doctor": "This doctor has no active assignment for laboratory orders."}
        )
    if assignment_count > 1:
        raise ValidationError(
            {
                "doctor": (
                    "This doctor has multiple possible active assignments. "
                    "Choose an explicit hospital and branch context."
                )
            }
        )

    assignment = assignments.get()
    return assignment.hospital_id, assignment.branch_id


def lab_staff_order_queryset(
    user: Any,
    queryset: QuerySet | None = None,
) -> QuerySet:
    base = queryset if queryset is not None else LabOrder.objects.all()

    if is_platform_admin(user):
        return base

    assignments = active_staff_assignments(
        user,
        role=StaffAssignment.Roles.LAB_TECHNICIAN,
    )

    if not assignments.exists():
        return base.none()

    return base.filter(_tenant_scope_q(assignments)).distinct()


def doctor_order_queryset(
    user: Any,
    doctor: Doctor,
    queryset: QuerySet | None = None,
) -> QuerySet:
    base = queryset if queryset is not None else LabOrder.objects.all()
    base = base.filter(doctor=doctor)

    if is_platform_admin(user):
        return base

    assignments = active_staff_assignments(
        user,
        role=StaffAssignment.Roles.DOCTOR,
    )

    if not assignments.exists():
        return base.none()

    return base.filter(_tenant_scope_q(assignments)).distinct()


def lab_staff_result_queryset(
    user: Any,
    queryset: QuerySet | None = None,
) -> QuerySet:
    base = queryset if queryset is not None else LabResult.objects.all()

    return base.filter(
        order_id__in=lab_staff_order_queryset(
            user,
            LabOrder.objects.values_list("pk", flat=True),
        )
    )


def doctor_result_queryset(
    user: Any,
    doctor: Doctor,
    queryset: QuerySet | None = None,
) -> QuerySet:
    base = queryset if queryset is not None else LabResult.objects.all()

    return base.filter(
        order_id__in=doctor_order_queryset(
            user,
            doctor,
            LabOrder.objects.values_list("pk", flat=True),
        )
    )


def doctor_appointment_queryset(user: Any, doctor: Doctor) -> QuerySet:
    from appointments.models import Appointment

    if is_platform_admin(user):
        appointment_scope = Q()
    else:
        appointment_scope = Q(pk__in=[])
        for assignment in active_staff_assignments(
            user,
            role=StaffAssignment.Roles.DOCTOR,
        ):
            if assignment.branch_id:
                appointment_scope |= Q(branch_id=assignment.branch_id)
            else:
                appointment_scope |= Q(hospital_id=assignment.hospital_id)
                appointment_scope |= Q(branch__hospital_id=assignment.hospital_id)

    return (
        Appointment.objects.filter(
            appointment_scope,
            doctor=doctor,
        )
        .select_related("patient", "doctor", "hospital", "branch")
        .distinct()
    )


def doctor_patient_queryset(user: Any, doctor: Doctor) -> QuerySet:
    appointment_qs = doctor_appointment_queryset(user, doctor)

    return (
        Patient.objects.filter(
            Q(doctor=doctor)
            | Q(appointments__in=appointment_qs)
        )
        .distinct()
        .order_by("full_name", "pk")
    )


def appointment_matches_patient(appointment: Any, patient: Patient) -> bool:
    return bool(
        appointment is None
        or getattr(appointment, "patient_id", None) == patient.pk
    )
