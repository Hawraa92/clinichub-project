from django.db.models import Q

from appointments.models import Appointment
from doctor.models import Doctor
from hospital.models import (
    Branch,
    Department,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient


def _is_authenticated(user):
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
    )


def _user_role(user):
    return getattr(user, "role", None)


def assigned_doctor_for(user):
    if not _is_authenticated(user):
        return None

    if getattr(user, "is_superuser", False):
        return None

    role = _user_role(user)

    if role == "doctor":
        return (
            Doctor.objects
            .select_related("user")
            .filter(user=user)
            .first()
        )

    if role != "secretary":
        return None

    direct = getattr(user, "assigned_doctor", None)

    if isinstance(direct, Doctor):
        return direct

    direct_id = getattr(
        user,
        "assigned_doctor_id",
        None,
    )

    if direct_id:
        return (
            Doctor.objects
            .select_related("user")
            .filter(pk=direct_id)
            .first()
        )

    return None


def active_location_assignments(user):
    if not _is_authenticated(user):
        return StaffAssignment.objects.none()

    allowed_roles = (
        StaffAssignment.Roles.HOSPITAL_ADMIN,
        StaffAssignment.Roles.SECRETARY,
        StaffAssignment.Roles.RECEPTIONIST,
        StaffAssignment.Roles.DOCTOR,
    )

    return (
        StaffAssignment.objects
        .filter(
            user=user,
            role__in=allowed_roles,
            is_active=True,
        )
        .select_related(
            "hospital",
            "branch",
            "department",
        )
        .order_by(
            "-is_primary",
            "pk",
        )
    )


def _build_location_scope(assignments):
    scope = None

    for assignment in assignments:
        if assignment.department_id:
            current_scope = Q(
                department_id=assignment.department_id
            )

        elif assignment.branch_id:
            current_scope = Q(
                branch_id=assignment.branch_id
            )

        else:
            current_scope = Q(
                hospital_id=assignment.hospital_id
            )

        scope = (
            current_scope
            if scope is None
            else scope | current_scope
        )

    return scope


def filter_appointments_for_user(queryset, user):
    if not _is_authenticated(user):
        return queryset.none()

    if getattr(user, "is_superuser", False):
        return queryset

    role = _user_role(user)
    assigned_doctor = assigned_doctor_for(user)

    assignments = list(
        active_location_assignments(user)
    )

    if role == "doctor":
        if assigned_doctor is None:
            return queryset.none()

        queryset = queryset.filter(
            doctor=assigned_doctor
        )

        if assignments:
            location_scope = _build_location_scope(
                assignments
            )

            queryset = queryset.filter(
                location_scope
            )

        return queryset.distinct()

    if role == "secretary":
        if assigned_doctor is None:
            return queryset.none()

        queryset = queryset.filter(
            doctor=assigned_doctor
        )

        if assignments:
            location_scope = _build_location_scope(
                assignments
            )

            queryset = queryset.filter(
                location_scope
            )

        return queryset.distinct()

    if assignments:
        location_scope = _build_location_scope(
            assignments
        )

        return queryset.filter(
            location_scope
        ).distinct()

    return queryset.none()


def filter_doctors_for_user(queryset, user):
    if not _is_authenticated(user):
        return queryset.none()

    if getattr(user, "is_superuser", False):
        return queryset

    role = _user_role(user)
    assigned_doctor = assigned_doctor_for(user)

    if role in ("doctor", "secretary"):
        if assigned_doctor is None:
            return queryset.none()

        return queryset.filter(
            pk=assigned_doctor.pk
        )

    assignments = list(
        active_location_assignments(user)
    )

    if not assignments:
        return queryset.none()

    doctor_scope = None

    for assignment in assignments:
        current_scope = Q(
            user__hospital_assignments__role=(
                StaffAssignment.Roles.DOCTOR
            ),
            user__hospital_assignments__is_active=True,
        )

        if assignment.department_id:
            current_scope &= Q(
                user__hospital_assignments__department_id=(
                    assignment.department_id
                )
            )

        elif assignment.branch_id:
            current_scope &= Q(
                user__hospital_assignments__branch_id=(
                    assignment.branch_id
                )
            )

        else:
            current_scope &= Q(
                user__hospital_assignments__hospital_id=(
                    assignment.hospital_id
                )
            )

        doctor_scope = (
            current_scope
            if doctor_scope is None
            else doctor_scope | current_scope
        )

    return queryset.filter(
        doctor_scope
    ).distinct()


def filter_patients_for_user(queryset, user):
    if not _is_authenticated(user):
        return queryset.none()

    if getattr(user, "is_superuser", False):
        return queryset

    role = _user_role(user)
    assigned_doctor = assigned_doctor_for(user)

    if role in ("doctor", "secretary"):
        if assigned_doctor is None:
            return queryset.none()

        return queryset.filter(
            doctor=assigned_doctor
        ).distinct()

    appointments = filter_appointments_for_user(
        Appointment.objects.all(),
        user,
    )

    return queryset.filter(
        appointments__in=appointments
    ).distinct()


def location_querysets_for_user(user):
    if not _is_authenticated(user):
        return {
            "hospital_queryset": Hospital.objects.none(),
            "branch_queryset": Branch.objects.none(),
            "department_queryset": Department.objects.none(),
        }

    if getattr(user, "is_superuser", False):
        return {
            "hospital_queryset": Hospital.objects.filter(
                is_active=True
            ),
            "branch_queryset": Branch.objects.filter(
                is_active=True
            ),
            "department_queryset": Department.objects.filter(
                is_active=True
            ),
        }

    appointments = filter_appointments_for_user(
        Appointment.objects.all(),
        user,
    )

    hospital_ids = appointments.exclude(
        hospital_id=None
    ).values_list(
        "hospital_id",
        flat=True,
    )

    branch_ids = appointments.exclude(
        branch_id=None
    ).values_list(
        "branch_id",
        flat=True,
    )

    department_ids = appointments.exclude(
        department_id=None
    ).values_list(
        "department_id",
        flat=True,
    )

    return {
        "hospital_queryset": Hospital.objects.filter(
            pk__in=hospital_ids,
            is_active=True,
        ).distinct(),
        "branch_queryset": Branch.objects.filter(
            pk__in=branch_ids,
            is_active=True,
        ).distinct(),
        "department_queryset": Department.objects.filter(
            pk__in=department_ids,
            is_active=True,
        ).distinct(),
    }


def ecg_form_querysets_for_user(user):
    querysets = {
        "patient_queryset": filter_patients_for_user(
            Patient.objects.all(),
            user,
        ),
        "doctor_queryset": filter_doctors_for_user(
            Doctor.objects.all(),
            user,
        ),
        "appointment_queryset": filter_appointments_for_user(
            Appointment.objects.all(),
            user,
        ),
    }

    querysets.update(
        location_querysets_for_user(user)
    )

    return querysets