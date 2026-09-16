from django.contrib.auth.models import Permission


def grant_archive_permissions(
    user,
    *,
    allow_create=False,
):
    """
    Grant only the permissions required by archive tests.
    Production permissions are not bypassed or weakened.
    """

    codenames = {
        "view_patientarchive",
        "view_archiveattachment",
        "view_archivevoicenote",
    }

    if allow_create:
        codenames.add("add_patientarchive")

    permissions = list(
        Permission.objects.filter(
            content_type__app_label="medical_archive",
            codename__in=sorted(codenames),
        )
    )

    found = {
        permission.codename
        for permission in permissions
    }
    missing = codenames - found

    if missing:
        raise AssertionError(
            f"Missing archive permissions: {sorted(missing)}"
        )

    user.user_permissions.add(*permissions)

    for cache_name in (
        "_perm_cache",
        "_user_perm_cache",
        "_group_perm_cache",
    ):
        user.__dict__.pop(cache_name, None)
