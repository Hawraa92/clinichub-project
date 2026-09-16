from __future__ import annotations

from django.conf import settings
from django.db.models import Q

from appointments.models import Appointment
from hospital.models import StaffAssignment


def secretary_can_access_prescriptions() -> bool:
    return bool(getattr(settings, "PRESCRIPTION_SECRETARY_CAN_VIEW", False))


def active_hospital_admin_assignments(user):
    if (
        not getattr(user, "is_authenticated", False)
        or getattr(user, "role", None) != "admin"
    ):
        return StaffAssignment.objects.none()

    return (
        StaffAssignment.objects.filter(
            user=user,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_active=True,
            is_deleted=False,
            hospital__is_active=True,
            hospital__is_deleted=False,
        )
        .filter(
            Q(branch__isnull=True)
            | Q(
                branch__is_active=True,
                branch__is_deleted=False,
            )
        )
    )


def admin_tenant_q(user, prefix: str = "") -> Q:
    scope = Q(pk__in=[])
    for assignment in active_hospital_admin_assignments(user):
        if assignment.branch_id is not None:
            scope |= Q(**{f"{prefix}branch_id": assignment.branch_id})
        else:
            scope |= Q(**{f"{prefix}hospital_id": assignment.hospital_id})
    return scope


def appointment_in_admin_scope(user, appointment: Appointment) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "role", None) != "admin":
        return False
    return Appointment.objects.filter(pk=appointment.pk).filter(
        admin_tenant_q(user)
    ).exists()


def active_secretary_assignments(user):
    if (
        not getattr(user, "is_authenticated", False)
        or getattr(user, "role", None) != "secretary"
    ):
        return StaffAssignment.objects.none()

    return (
        StaffAssignment.objects.filter(
            user=user,
            role=StaffAssignment.Roles.SECRETARY,
            is_active=True,
            is_deleted=False,
            hospital__is_active=True,
            hospital__is_deleted=False,
        )
        .filter(
            Q(branch__isnull=True)
            | Q(
                branch__is_active=True,
                branch__is_deleted=False,
            )
        )
        .filter(
            Q(department__isnull=True)
            | Q(
                department__is_active=True,
                department__is_deleted=False,
                department__branch__is_active=True,
                department__branch__is_deleted=False,
            )
        )
    )


def secretary_tenant_q(user, prefix: str = "") -> Q:
    scope = Q(pk__in=[])
    for assignment in active_secretary_assignments(user):
        if assignment.department_id is not None:
            scope |= Q(**{f"{prefix}department_id": assignment.department_id})
        elif assignment.branch_id is not None:
            scope |= Q(**{f"{prefix}branch_id": assignment.branch_id})
        else:
            scope |= Q(**{f"{prefix}hospital_id": assignment.hospital_id})
    return scope


def appointment_in_secretary_scope(user, appointment: Appointment) -> bool:
    if not secretary_can_access_prescriptions():
        return False
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "role", None) != "secretary":
        return False
    return Appointment.objects.filter(pk=appointment.pk).filter(
        secretary_tenant_q(user)
    ).exists()