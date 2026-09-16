from __future__ import annotations

from django.contrib.auth.models import Permission

from accounts.permissions_views import (
    _managed_permissions_queryset,
    _role_preset_permission_ids,
)


def apply_role_permissions(user) -> None:
    """Apply the ClinicHub role preset to a test user."""
    managed_permissions = list(
        _managed_permissions_queryset()
    )

    permission_ids = _role_preset_permission_ids(
        role=getattr(user, "role", ""),
        permissions=managed_permissions,
    )

    user.user_permissions.add(
        *Permission.objects.filter(
            pk__in=permission_ids
        )
    )

    for cache_name in (
        "_perm_cache",
        "_user_perm_cache",
        "_group_perm_cache",
    ):
        user.__dict__.pop(cache_name, None)
