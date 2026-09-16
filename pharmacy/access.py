from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet

from hospital.models import StaffAssignment

from .models import (
    Pharmacy,
    PharmacyOrder,
    PharmacyStaffAssignment,
)


def is_platform_admin(user: Any) -> bool:
    """
    Only a Django superuser is a global ClinicHub administrator.

    A normal account whose role is ``admin`` remains tenant-scoped
    through an active HOSPITAL_ADMIN StaffAssignment.
    """
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )


def active_hospital_admin_assignments(
    user: Any,
) -> QuerySet:
    """
    Return the active hospital/branch scopes administered by the user.

    The account role and StaffAssignment role must both identify an
    administrator. A branch assignment is branch-scoped; an assignment
    without a branch covers the complete hospital.
    """
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
        .select_related(
            "hospital",
            "branch",
            "department",
        )
        .order_by(
            "-is_primary",
            "hospital__name",
            "branch__name",
            "pk",
        )
    )


def is_pharmacy_portal_user(user: Any) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if is_platform_admin(user):
        return True

    # A pharmacist may enter standalone setup before the first
    # PharmacyStaffAssignment has been created.
    if getattr(user, "role", None) == "pharmacist":
        return True

    return active_hospital_admin_assignments(
        user
    ).exists()


def active_pharmacy_assignments(user: Any) -> QuerySet:
    if not getattr(user, "is_authenticated", False):
        return PharmacyStaffAssignment.objects.none()

    return (
        PharmacyStaffAssignment.objects.filter(
            staff_assignment__user=user,
            staff_assignment__is_active=True,
            staff_assignment__is_deleted=False,
            is_active=True,
            is_deleted=False,
            pharmacy__is_active=True,
            pharmacy__is_deleted=False,
            pharmacy__branch__is_active=True,
            pharmacy__branch__is_deleted=False,
            pharmacy__branch__hospital__is_active=True,
            pharmacy__branch__hospital__is_deleted=False,
        )
        .select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "staff_assignment",
            "staff_assignment__user",
        )
        .order_by(
            "pharmacy__name",
            "-is_manager",
            "id",
        )
    )


def accessible_pharmacies(user: Any) -> QuerySet:
    base = Pharmacy.objects.filter(
        is_active=True,
        is_deleted=False,
        branch__is_active=True,
        branch__is_deleted=False,
        branch__hospital__is_active=True,
        branch__hospital__is_deleted=False,
    ).select_related(
        "branch",
        "branch__hospital",
    )

    if not getattr(user, "is_authenticated", False):
        return base.none()

    if is_platform_admin(user):
        return base.order_by(
            "branch__hospital__name",
            "branch__name",
            "name",
        )

    pharmacy_assignment_ids = (
        active_pharmacy_assignments(user)
        .values_list(
            "pharmacy_id",
            flat=True,
        )
    )

    admin_assignments = (
        active_hospital_admin_assignments(user)
    )

    hospital_ids = (
        admin_assignments
        .filter(branch__isnull=True)
        .values_list(
            "hospital_id",
            flat=True,
        )
    )

    branch_ids = (
        admin_assignments
        .filter(branch__isnull=False)
        .values_list(
            "branch_id",
            flat=True,
        )
    )

    access_scope = (
        Q(pk__in=pharmacy_assignment_ids)
        | Q(branch__hospital_id__in=hospital_ids)
        | Q(branch_id__in=branch_ids)
    )

    return (
        base.filter(access_scope)
        .distinct()
        .order_by(
            "branch__hospital__name",
            "branch__name",
            "name",
        )
    )


def assignment_for_order(
    user: Any,
    order: PharmacyOrder,
) -> PharmacyStaffAssignment | None:
    return (
        active_pharmacy_assignments(user)
        .filter(pharmacy_id=order.pharmacy_id)
        .order_by("-is_manager", "id")
        .first()
    )


def user_can_view_order(
    user: Any,
    order: PharmacyOrder,
) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if is_platform_admin(user):
        return True

    doctor_user_id = getattr(
        getattr(order.prescription, "doctor", None),
        "user_id",
        None,
    )

    if doctor_user_id == getattr(user, "pk", None):
        return True

    return accessible_pharmacies(user).filter(
        pk=order.pharmacy_id,
    ).exists()


def _hospital_admin_can_manage_prescription(
    user: Any,
    prescription: Any,
) -> bool:
    """
    A hospital administrator may manage a prescription only when its
    originating appointment is inside the administrator's location.
    """
    appointment = getattr(
        prescription,
        "appointment",
        None,
    )

    if appointment is None:
        return False

    hospital_id = getattr(
        appointment,
        "hospital_id",
        None,
    )
    branch_id = getattr(
        appointment,
        "branch_id",
        None,
    )

    if hospital_id is None:
        branch = getattr(
            appointment,
            "branch",
            None,
        )
        hospital_id = getattr(
            branch,
            "hospital_id",
            None,
        )

    if hospital_id is None and branch_id is None:
        return False

    for assignment in active_hospital_admin_assignments(
        user
    ):
        # A branch-scoped administrator must match that branch.
        if assignment.branch_id is not None:
            if (
                branch_id is not None
                and assignment.branch_id == branch_id
            ):
                return True

            continue

        # An assignment without a branch covers its hospital.
        if (
            hospital_id is not None
            and assignment.hospital_id == hospital_id
        ):
            return True

    return False


def user_can_manage_prescription(
    user: Any,
    prescription: Any,
) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if is_platform_admin(user):
        return True

    doctor_user_id = getattr(
        getattr(prescription, "doctor", None),
        "user_id",
        None,
    )

    if doctor_user_id == getattr(user, "pk", None):
        return True

    return _hospital_admin_can_manage_prescription(
        user,
        prescription,
    )


def pharmacy_portal_required(
    view_func: Callable,
) -> Callable:
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_pharmacy_portal_user(request.user):
            raise PermissionDenied(
                "Pharmacy access is restricted."
            )

        return view_func(
            request,
            *args,
            **kwargs,
        )

    return _wrapped
