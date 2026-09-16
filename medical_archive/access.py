from __future__ import annotations

from django.db.models import Q, QuerySet

from doctor.models import Doctor
from hospital.models import StaffAssignment
from patient.models import Patient

from .models import PatientArchive


STAFF_ACCOUNT_ROLES = {
    "admin",
    "secretary",
}


def _role(user):
    return getattr(user, "role", None)


def _staff_assignment_roles():
    roles = [
        StaffAssignment.Roles.HOSPITAL_ADMIN,
        StaffAssignment.Roles.SECRETARY,
    ]

    receptionist = getattr(
        StaffAssignment.Roles,
        "RECEPTIONIST",
        None,
    )

    if receptionist:
        roles.append(receptionist)

    return roles


def active_staff_assignments(user):
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or _role(user) not in STAFF_ACCOUNT_ROLES
    ):
        return StaffAssignment.objects.none()

    return (
        StaffAssignment.objects.filter(
            user=user,
            role__in=_staff_assignment_roles(),
            is_active=True,
        )
        .select_related(
            "hospital",
            "branch",
            "department",
        )
        .order_by("-is_primary", "pk")
    )


def _location_q(prefix, assignment):
    if assignment.department_id:
        return Q(
            **{
                f"{prefix}department_id":
                assignment.department_id
            }
        )

    if assignment.branch_id:
        return Q(
            **{
                f"{prefix}branch_id":
                assignment.branch_id
            }
        )

    return Q(
        **{
            f"{prefix}hospital_id":
            assignment.hospital_id
        }
    )


def _doctor_assignment_q(prefix, assignment):
    query = Q(
        **{
            f"{prefix}role":
            StaffAssignment.Roles.DOCTOR,
            f"{prefix}is_active":
            True,
        }
    )

    return query & _location_q(
        prefix,
        assignment,
    )


def _combined_scope(assignments, builder):
    scope = None

    for assignment in assignments:
        current = builder(assignment)
        scope = (
            current
            if scope is None
            else scope | current
        )

    return scope


def _archive_staff_scope(assignments):
    """
    Appointment-linked archives are scoped strictly by the
    appointment location.

    Doctor assignments are used only for legacy archives that
    do not have an appointment.
    """

    def build(assignment):
        appointment_scope = (
            Q(appointment__isnull=False)
            & _location_q(
                "appointment__",
                assignment,
            )
        )

        legacy_doctor_scope = (
            Q(appointment__isnull=True)
            & _doctor_assignment_q(
                "doctor__user__hospital_assignments__",
                assignment,
            )
        )

        return (
            appointment_scope
            | legacy_doctor_scope
        )

    return _combined_scope(
        assignments,
        build,
    )


def _patient_staff_scope(assignments):
    def build(assignment):
        appointment_scope = _location_q(
            "appointments__",
            assignment,
        )

        doctor_scope = _doctor_assignment_q(
            "doctor__user__hospital_assignments__",
            assignment,
        )

        return appointment_scope | doctor_scope

    return _combined_scope(assignments, build)


def _doctor_staff_scope(assignments):
    return _combined_scope(
        assignments,
        lambda assignment: _doctor_assignment_q(
            "user__hospital_assignments__",
            assignment,
        ),
    )


def _doctor_for_user(user):
    if user is None:
        return None

    return (
        Doctor.objects.select_related("user")
        .filter(user=user)
        .first()
    )


def filter_archives_for_user(qs, user):
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
    ):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    role = _role(user)

    if role == "doctor":
        return qs.filter(
            doctor__user=user
        ).distinct()

    if role == "patient":
        return qs.filter(
            patient__user=user
        ).distinct()

    if role in STAFF_ACCOUNT_ROLES:
        assignments = list(
            active_staff_assignments(user)
        )

        if not assignments:
            return qs.none()

        scope = _archive_staff_scope(
            assignments
        )

        # A genuinely unlocated legacy archive is visible
        # only to the staff user who originally created it.
        #
        # Appointment-linked or doctor-linked archives must
        # always remain restricted to the current tenant scope.
        legacy_creator_scope = Q(
            appointment__isnull=True,
            doctor__isnull=True,
            created_by=user,
        )

        return qs.filter(
            scope | legacy_creator_scope
        ).distinct()

    return qs.none()


def filter_patients_for_user(qs, user):
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
    ):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    role = _role(user)

    if role == "patient":
        return qs.filter(user=user)

    if role == "doctor":
        doctor = _doctor_for_user(user)

        if doctor is None:
            return qs.none()

        return qs.filter(
            Q(doctor=doctor)
            | Q(appointments__doctor=doctor)
            | Q(medical_archives__doctor=doctor)
        ).distinct()

    if role in STAFF_ACCOUNT_ROLES:
        assignments = list(
            active_staff_assignments(user)
        )

        if not assignments:
            return qs.none()

        scope = _patient_staff_scope(
            assignments
        )

        return qs.filter(scope).distinct()

    return qs.none()


def filter_doctors_for_user(qs, user):
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
    ):
        return qs.none()

    if getattr(user, "is_superuser", False):
        return qs

    role = _role(user)

    if role == "doctor":
        return qs.filter(user=user)

    if role in STAFF_ACCOUNT_ROLES:
        assignments = list(
            active_staff_assignments(user)
        )

        if not assignments:
            return qs.none()

        scope = _doctor_staff_scope(
            assignments
        )

        return qs.filter(scope).distinct()

    return qs.none()


def is_authorized_for_archive(user, archive):
    if archive is None:
        return False

    return filter_archives_for_user(
        PatientArchive.objects.all(),
        user,
    ).filter(pk=archive.pk).exists()


def can_edit_archive(user, archive):
    if (
        archive is None
        or user is None
        or not getattr(user, "is_authenticated", False)
    ):
        return False

    if getattr(user, "is_superuser", False):
        return True

    role = _role(user)

    if role == "doctor":
        return bool(
            archive.doctor_id
            and getattr(
                archive.doctor,
                "user_id",
                None,
            ) == user.id
        )

    if role in STAFF_ACCOUNT_ROLES:
        return is_authorized_for_archive(
            user,
            archive,
        )

    return False
