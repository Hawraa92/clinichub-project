from __future__ import annotations

from django.core.exceptions import PermissionDenied


def is_license_administrator(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        user.is_superuser
        or user.has_perm("licensing.change_licenserecord")
    )


def require_license_administrator(user) -> None:
    if not is_license_administrator(user):
        raise PermissionDenied("Only a ClinicHub administrator can manage licenses.")
