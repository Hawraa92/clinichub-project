from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from hospital.models import StaffAssignment


User = get_user_model()

USERS_PER_PAGE = 25


MANAGED_MODULES = (
    {
        "app_label": "patient",
        "label": "إدارة المرضى",
        "description": "ملفات المرضى والبيانات الطبية المرتبطة بهم.",
        "icon": "bi-people",
    },
    {
        "app_label": "doctor",
        "label": "إدارة الأطباء",
        "description": "حسابات الأطباء ولوحاتهم وبيانات عملهم.",
        "icon": "bi-person-badge",
    },
    {
        "app_label": "appointments",
        "label": "المواعيد",
        "description": "الحجز وجدولة المواعيد والطوابير.",
        "icon": "bi-calendar2-check",
    },
    {
        "app_label": "prescription",
        "label": "الوصفات الطبية",
        "description": "إنشاء الوصفات وعرضها وإدارتها.",
        "icon": "bi-file-medical",
    },
    {
        "app_label": "pharmacy",
        "label": "الصيدلية",
        "description": "الأدوية والمخزون والطلبات والصرف.",
        "icon": "bi-capsule",
    },
    {
    "app_label": "lab",
    "label": "المختبر",
    "description": "طلبات الفحوصات والنتائج المختبرية.",
    "icon": "bi-eyedropper",
    },
    {
        "app_label": "medical_archive",
        "label": "الأرشيف الطبي",
        "description": "المرفقات والوثائق والسجلات المؤرشفة.",
        "icon": "bi-archive",
    },
    {
        "app_label": "hospital",
        "label": "المؤسسات والفروع",
        "description": "المؤسسات والفروع والأقسام وتكليفات الموظفين.",
        "icon": "bi-buildings",
    },
    {
        "app_label": "licensing",
        "label": "التراخيص",
        "description": "تراخيص النظام والتفعيل وإدارة الاشتراكات.",
        "icon": "bi-key",
    },
    {
        "app_label": "accounts",
        "label": "الحسابات",
        "description": "حسابات المستخدمين والأدوار والموافقات.",
        "icon": "bi-person-gear",
    },
)


PERMISSION_ACTIONS = (
    {
        "key": "view",
        "label": "عرض",
        "icon": "bi-eye",
    },
    {
        "key": "add",
        "label": "إضافة",
        "icon": "bi-plus-circle",
    },
    {
        "key": "change",
        "label": "تعديل",
        "icon": "bi-pencil-square",
    },
    {
        "key": "delete",
        "label": "حذف",
        "icon": "bi-trash3",
    },
)


MANAGED_APP_LABELS = tuple(
    module["app_label"]
    for module in MANAGED_MODULES
)


VALID_PERMISSION_ACTIONS = {
    action["key"]
    for action in PERMISSION_ACTIONS
}


# ---------------------------------------------------------------------------
# Ready-made permission presets
# ---------------------------------------------------------------------------
#
# Each preset contains only the minimum permissions normally required by the
# selected role. Applying a preset replaces the user's managed direct
# permissions while preserving permissions outside MANAGED_MODULES.
#
# Data scope must still be enforced by each application's views. For example,
# a doctor can receive view_patientarchive, while the archive views restrict
# that doctor to their own records.
#
# Medical archive policy:
# - Doctors: view, add and change their own archives; no archive deletion.
# - Secretaries, pharmacists, lab staff and patients: no archive access.
# - Platform superusers bypass model permissions as usual.
#
ROLE_PERMISSION_PRESETS: dict[str, dict[str, Any]] = {
    "admin": {
        "label": "Clinic Administrator",
        "description": (
            "Full access to all ClinicHub modules managed by this screen."
        ),
        "all_managed_permissions": True,
        "rules": (),
    },
    "doctor": {
        "label": "Doctor",
        "description": (
            "Clinical access for patients, appointments, prescriptions, "
            "laboratory requests and the doctor's own medical archives."
        ),
        "all_managed_permissions": False,
        "rules": (
            (
                "patient",
                ("patient",),
                ("view",),
            ),
            (
                "doctor",
                ("specialty",),
                ("view",),
            ),
            (
                "doctor",
                ("doctor",),
                ("view", "change"),
            ),
            (
                "doctor",
                (
                    "doctorvisit",
                    "doctorreview",
                ),
                ("view", "add", "change"),
            ),
            (
                "doctor",
                ("patientreportexportaccess",),
                ("view",),
            ),
            (
                "appointments",
                ("appointment",),
                ("view", "add", "change"),
            ),
            (
                "appointments",
                ("patientbookingrequest",),
                ("view", "change"),
            ),
            (
                "appointments",
                ("notification",),
                ("view",),
            ),
            (
                "prescription",
                (
                    "prescription",
                    "medication",
                ),
                ("view", "add", "change"),
            ),
            (
                "pharmacy",
                ("pharmacyorder",),
                ("view", "add"),
            ),
            (
                "lab",
                ("laborder",),
                ("view", "add", "change"),
            ),
            (
                "lab",
                ("labresult",),
                ("view",),
            ),
            (
                "medical_archive",
                ("patientarchive",),
                ("view", "add", "change"),
            ),
            (
                "medical_archive",
                ("archiveattachment",),
                ("view", "add"),
            ),
            (
                "medical_archive",
                ("archivevoicenote",),
                ("view", "add"),
            ),
        ),
    },
    "secretary": {
        "label": "Secretary",
        "description": (
            "Front-desk access for patients, bookings, appointments and "
            "queue operations. Medical archives are excluded."
        ),
        "all_managed_permissions": False,
        "rules": (
            (
                "patient",
                ("patient",),
                ("view", "add", "change"),
            ),
            (
                "doctor",
                (
                    "specialty",
                    "doctor",
                ),
                ("view",),
            ),
                        (
                "appointments",
                ("appointment",),
                ("view", "add", "change", "delete"),
            ),

            (
                "appointments",
                ("patientbookingrequest",),
                ("view", "change"),
            ),
            (
                "appointments",
                ("notification",),
                ("view",),
            ),
        ),
    },
    "pharmacist": {
        "label": "Pharmacist",
        "description": (
            "Pharmacy operations, prescription review, dispensing and "
            "inventory management without destructive delete access."
        ),
        "all_managed_permissions": False,
        "rules": (
            (
                "patient",
                ("patient",),
                ("view",),
            ),
            (
                "doctor",
                ("doctor",),
                ("view",),
            ),
            (
                "prescription",
                (
                    "prescription",
                    "medication",
                ),
                ("view",),
            ),
            (
                "pharmacy",
                ("pharmacy",),
                ("view",),
            ),
            (
                "pharmacy",
                (
                    "dispenseitem",
                    "dispense",
                    "medicine",
                    "pharmacyinventory",
                    "pharmacyorderitem",
                    "pharmacyorder",
                    "pharmacysaleallocation",
                    "pharmacysaleitem",
                    "pharmacysale",
                    "pharmacystaffassignment",
                    "stockbatch",
                    "stockmovement",
                ),
                ("view", "add", "change"),
            ),
        ),
    },
    "lab": {
        "label": "Laboratory Staff",
        "description": (
            "Laboratory orders and results with limited patient and doctor "
            "lookup access. Medical archives are excluded."
        ),
        "all_managed_permissions": False,
        "rules": (
            (
                "patient",
                ("patient",),
                ("view",),
            ),
            (
                "doctor",
                ("doctor",),
                ("view",),
            ),
            (
                "lab",
                ("labsettings",),
                ("view",),
            ),
            (
                "lab",
                ("laborder",),
                ("view", "change"),
            ),
            (
                "lab",
                ("labresult",),
                ("view", "add", "change"),
            ),
        ),
    },
    "patient": {
        "label": "Patient",
        "description": (
            "Patient self-service access for the user's own profile, "
            "bookings, appointments, prescriptions and laboratory results."
        ),
        "all_managed_permissions": False,
        "rules": (
            (
                "patient",
                ("patient",),
                ("view", "change"),
            ),
            (
                "doctor",
                (
                    "specialty",
                    "doctor",
                ),
                ("view",),
            ),
            (
                "appointments",
                ("appointment",),
                ("view",),
            ),
            (
                "appointments",
                ("patientbookingrequest",),
                ("view", "add", "change"),
            ),
            (
                "appointments",
                ("notification",),
                ("view",),
            ),
            (
                "prescription",
                (
                    "prescription",
                    "medication",
                ),
                ("view",),
            ),
            (
                "lab",
                (
                    "laborder",
                    "labresult",
                ),
                ("view",),
            ),
            (
                "medical_archive",
                ("patientarchive",),
                ("view",),
            ),
        ),
    },
}


def _ensure_platform_superuser(request) -> None:
    """
    Prevent any user other than the platform superuser from managing
    user permissions.
    """
    if not (
        request.user.is_authenticated
        and request.user.is_superuser
    ):
        raise PermissionDenied(
            "Only the platform superuser can manage user permissions."
        )


def _get_query_value(
    request,
    name: str,
) -> str:
    """
    Read a safe text value from the query string.
    """
    value = request.GET.get(name, "")

    if value is None:
        return ""

    return str(value).strip()


def _managed_permissions_queryset() -> QuerySet:
    """
    Return permissions managed through the ClinicHub interface.

    Django internal apps such as auth and contenttypes are excluded.
    """
    return (
        Permission.objects.filter(
            content_type__app_label__in=MANAGED_APP_LABELS,
        )
        .select_related(
            "content_type",
        )
        .order_by(
            "content_type__app_label",
            "content_type__model",
            "codename",
            "pk",
        )
    )


def _safe_permission_ids(
    raw_values: Iterable[Any],
) -> set[int]:
    """
    Convert submitted permission IDs to a safe integer set.
    """
    permission_ids: set[int] = set()

    for raw_value in raw_values:
        try:
            permission_id = int(raw_value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            continue

        if permission_id > 0:
            permission_ids.add(permission_id)

    return permission_ids


def _permission_action(
    codename: str,
) -> str | None:
    """
    Extract the standard Django action from a permission codename.

    Examples:
    view_patient   -> view
    add_patient    -> add
    change_patient -> change
    delete_patient -> delete
    """
    action = str(codename or "").split(
        "_",
        1,
    )[0]

    if action in VALID_PERMISSION_ACTIONS:
        return action

    return None


def _role_preset_permission_ids(
    *,
    role: str,
    permissions: Iterable[Permission],
) -> set[int]:
    """
    Resolve managed permission IDs belonging to a role preset.

    Presets use app labels, model names and standard Django actions
    instead of database IDs, keeping them stable between databases.
    """
    preset = ROLE_PERMISSION_PRESETS.get(
        str(role or "").strip().lower()
    )

    if not preset:
        return set()

    permissions_list = list(permissions)

    if preset.get("all_managed_permissions"):
        return {
            permission.pk
            for permission in permissions_list
        }

    selected_ids: set[int] = set()
    rules = preset.get("rules", ())

    for permission in permissions_list:
        app_label = (
            permission.content_type.app_label
        )
        model_name = (
            permission.content_type.model
        )
        action = _permission_action(
            permission.codename
        )

        if action is None:
            continue

        for (
            rule_app_label,
            rule_models,
            rule_actions,
        ) in rules:
            model_matches = (
                "*" in rule_models
                or model_name in rule_models
            )

            if (
                app_label == rule_app_label
                and model_matches
                and action in rule_actions
            ):
                selected_ids.add(
                    permission.pk
                )
                break

    return selected_ids


def _build_role_preset_options(
    *,
    permissions: Iterable[Permission],
) -> list[dict[str, Any]]:
    """
    Build role preset options for the permission editor.
    """
    permissions_list = list(permissions)
    options: list[dict[str, Any]] = []

    for role_value, role_label in User.Roles.choices:
        preset = ROLE_PERMISSION_PRESETS.get(
            role_value
        )

        if not preset:
            continue

        permission_ids = (
            _role_preset_permission_ids(
                role=role_value,
                permissions=permissions_list,
            )
        )

        options.append(
            {
                "value": role_value,
                "role_label": str(role_label),
                "label": preset["label"],
                "description": (
                    preset["description"]
                ),
                "permission_count": len(
                    permission_ids
                ),
            }
        )

    return options


def _model_display_name(
    permission: Permission,
) -> str:
    """
    Return a readable model name for a permission.
    """
    model_class = permission.content_type.model_class()

    if model_class is not None:
        return str(
            model_class._meta.verbose_name_plural
        )

    return str(
        permission.content_type.model
    ).replace(
        "_",
        " ",
    ).title()


def _permission_item(
    permission: Permission,
    *,
    direct_permission_ids: set[int],
    group_permission_ids: set[int],
) -> dict[str, Any]:
    """
    Prepare one permission for display inside a checkbox.
    """
    is_direct = (
        permission.pk in direct_permission_ids
    )
    is_inherited = (
        permission.pk in group_permission_ids
    )

    return {
        "id": permission.pk,
        "name": str(permission.name),
        "codename": permission.codename,
        "is_direct": is_direct,
        "is_inherited": is_inherited,
        "is_effective": (
            is_direct or is_inherited
        ),
    }


def _build_permission_modules(
    *,
    permissions: Iterable[Permission],
    direct_permission_ids: set[int],
    group_permission_ids: set[int],
) -> list[dict[str, Any]]:
    """
    Convert Django permissions into:

    module -> model -> view/add/change/delete

    Group permissions appear as inherited while direct permissions
    remain editable through the interface.
    """
    permissions_by_app: dict[
        str,
        list[Permission],
    ] = defaultdict(list)

    for permission in permissions:
        permissions_by_app[
            permission.content_type.app_label
        ].append(permission)

    modules: list[dict[str, Any]] = []

    for module_config in MANAGED_MODULES:
        app_label = module_config["app_label"]
        app_permissions = permissions_by_app.get(
            app_label,
            [],
        )

        if not app_permissions:
            continue

        model_map: dict[
            int,
            dict[str, Any],
        ] = {}

        module_permission_ids: set[int] = set()

        for permission in app_permissions:
            content_type_id = (
                permission.content_type_id
            )

            model_data = model_map.setdefault(
                content_type_id,
                {
                    "content_type_id": (
                        content_type_id
                    ),
                    "model_key": (
                        permission.content_type.model
                    ),
                    "model_label": (
                        _model_display_name(
                            permission
                        )
                    ),
                    "action_map": {},
                    "custom_permissions": [],
                },
            )

            permission_data = _permission_item(
                permission,
                direct_permission_ids=(
                    direct_permission_ids
                ),
                group_permission_ids=(
                    group_permission_ids
                ),
            )

            action = _permission_action(
                permission.codename
            )

            if action:
                model_data["action_map"][
                    action
                ] = permission_data
            else:
                model_data[
                    "custom_permissions"
                ].append(permission_data)

            module_permission_ids.add(
                permission.pk
            )

        model_rows: list[dict[str, Any]] = []

        for model_data in sorted(
            model_map.values(),
            key=lambda item: (
                str(
                    item["model_label"]
                ).lower(),
                item["content_type_id"],
            ),
        ):
            action_cells = []

            for action_config in PERMISSION_ACTIONS:
                action_key = action_config["key"]

                action_cells.append(
                    {
                        "key": action_key,
                        "label": (
                            action_config["label"]
                        ),
                        "icon": (
                            action_config["icon"]
                        ),
                        "permission": (
                            model_data[
                                "action_map"
                            ].get(action_key)
                        ),
                    }
                )

            model_rows.append(
                {
                    "content_type_id": (
                        model_data[
                            "content_type_id"
                        ]
                    ),
                    "model_key": (
                        model_data["model_key"]
                    ),
                    "model_label": (
                        model_data["model_label"]
                    ),
                    "actions": action_cells,
                    "custom_permissions": (
                        model_data[
                            "custom_permissions"
                        ]
                    ),
                }
            )

        direct_in_module = (
            module_permission_ids
            & direct_permission_ids
        )
        inherited_in_module = (
            module_permission_ids
            & group_permission_ids
        )
        effective_in_module = (
            direct_in_module
            | inherited_in_module
        )

        modules.append(
            {
                **module_config,
                "models": model_rows,
                "permission_ids": sorted(
                    module_permission_ids
                ),
                "permission_count": len(
                    module_permission_ids
                ),
                "direct_count": len(
                    direct_in_module
                ),
                "inherited_count": len(
                    inherited_in_module
                ),
                "effective_count": len(
                    effective_in_module
                ),
                "all_direct_selected": bool(
                    module_permission_ids
                )
                and module_permission_ids.issubset(
                    direct_permission_ids
                ),
                "has_direct_selection": bool(
                    direct_in_module
                ),
                "has_partial_direct_selection": (
                    bool(direct_in_module)
                    and not module_permission_ids.issubset(
                        direct_permission_ids
                    )
                ),
            }
        )

    return modules


def _active_assignments_queryset() -> QuerySet:
    """
    Return active staff assignments with their work scope.
    """
    return (
        StaffAssignment.objects.filter(
            is_active=True,
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
            "department__name",
            "pk",
        )
    )


@login_required
@require_GET
def permissions_dashboard(request):
    """
    Superuser user-management dashboard.

    Supports:
    - Name or email search.
    - Role filtering.
    - Account status filtering.
    - Pagination.
    """
    _ensure_platform_superuser(request)

    search_query = _get_query_value(
        request,
        "q",
    )
    selected_role = _get_query_value(
        request,
        "role",
    ).lower()
    selected_status = _get_query_value(
        request,
        "status",
    ).lower()

    valid_roles = {
        value
        for value, _label in User.Roles.choices
    }

    users = (
        User.objects.filter(
            is_superuser=False,
        )
        .annotate(
            direct_permission_count=Count(
                "user_permissions",
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "hospital_assignments",
                queryset=(
                    _active_assignments_queryset()
                ),
                to_attr=(
                    "active_access_assignments"
                ),
            ),
        )
        .order_by(
            "first_name",
            "last_name",
            "email",
            "pk",
        )
    )

    if search_query:
        users = users.filter(
            Q(
                email__icontains=search_query
            )
            | Q(
                username__icontains=search_query
            )
            | Q(
                first_name__icontains=search_query
            )
            | Q(
                last_name__icontains=search_query
            )
        )

    if selected_role in valid_roles:
        users = users.filter(
            role=selected_role,
        )
    else:
        selected_role = ""

    if selected_status == "active":
        users = users.filter(
            is_active=True,
        )
    elif selected_status == "inactive":
        users = users.filter(
            is_active=False,
        )
    elif selected_status == "approved":
        users = users.filter(
            is_approved=True,
        )
    elif selected_status == "pending":
        users = users.filter(
            is_approved=False,
        )
    else:
        selected_status = ""

    paginator = Paginator(
        users,
        USERS_PER_PAGE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page"),
    )

    context = {
        "page_obj": page_obj,
        "search_query": search_query,
        "selected_role": selected_role,
        "selected_status": selected_status,
        "role_choices": User.Roles.choices,
        "total_results": paginator.count,
    }

    return render(
        request,
        "accounts/permissions/dashboard.html",
        context,
    )


@login_required
@require_http_methods(
    [
        "GET",
        "POST",
    ]
)
def user_permissions_edit(
    request,
    user_id: int,
):
    """
    Edit one user's account and direct permissions.

    Group permissions remain inherited and are displayed to the superuser.
    Permissions outside the managed ClinicHub apps are preserved.
    """
    _ensure_platform_superuser(request)

    target_user = get_object_or_404(
        User.objects.filter(
            is_superuser=False,
        ),
        pk=user_id,
    )

    managed_permissions = list(
        _managed_permissions_queryset()
    )

    managed_permission_ids = {
        permission.pk
        for permission in managed_permissions
    }

    if request.method == "POST":
        submit_action = str(
            request.POST.get(
                "submit_action",
                "save",
            )
            or "save"
        ).strip().lower()

        selected_role = str(
            request.POST.get(
                "role",
                target_user.role,
            )
            or ""
        ).strip()

        valid_roles = {
            value
            for value, _label
            in User.Roles.choices
        }

        if selected_role not in valid_roles:
            messages.error(
                request,
                "The selected role is invalid.",
            )

            return redirect(
                "accounts:user_permissions_edit",
                user_id=target_user.pk,
            )

        if submit_action == "apply_role_preset":
            if (
                selected_role
                not in ROLE_PERMISSION_PRESETS
            ):
                messages.error(
                    request,
                    (
                        "No permission preset is "
                        "available for the selected role."
                    ),
                )

                return redirect(
                    "accounts:user_permissions_edit",
                    user_id=target_user.pk,
                )

            selected_managed_ids = (
                _role_preset_permission_ids(
                    role=selected_role,
                    permissions=managed_permissions,
                )
            )
        else:
            requested_permission_ids = (
                _safe_permission_ids(
                    request.POST.getlist(
                        "permissions"
                    )
                )
            )

            selected_managed_ids = (
                requested_permission_ids
                & managed_permission_ids
            )

        with transaction.atomic():
            current_direct_ids = set(
                target_user.user_permissions.values_list(
                    "pk",
                    flat=True,
                )
            )

            preserved_unmanaged_ids = (
                current_direct_ids
                - managed_permission_ids
            )

            final_permission_ids = (
                preserved_unmanaged_ids
                | selected_managed_ids
            )

            target_user.role = selected_role
            target_user.is_active = (
                "is_active"
                in request.POST
            )
            target_user.is_approved = (
                "is_approved"
                in request.POST
            )
            target_user.is_staff = (
                "is_staff"
                in request.POST
            )

            target_user.save(
                update_fields=[
                    "role",
                    "is_active",
                    "is_approved",
                    "is_staff",
                ]
            )

            final_permissions = (
                Permission.objects.filter(
                    pk__in=final_permission_ids,
                )
            )

            target_user.user_permissions.set(
                final_permissions
            )

        if submit_action == "apply_role_preset":
            preset_label = (
                ROLE_PERMISSION_PRESETS[
                    selected_role
                ]["label"]
            )

            messages.success(
                request,
                (
                    f'The "{preset_label}" permission '
                    f"preset was applied to {target_user}."
                ),
            )
        else:
            messages.success(
                request,
                (
                    f"Account and permissions for "
                    f"{target_user} were updated successfully."
                ),
            )

        return redirect(
            "accounts:user_permissions_edit",
            user_id=target_user.pk,
        )

    direct_permission_ids = set(
        target_user.user_permissions.values_list(
            "pk",
            flat=True,
        )
    )

    group_permission_ids = {
        permission_id
        for permission_id
        in target_user.groups.values_list(
            "permissions__pk",
            flat=True,
        )
        if permission_id is not None
    }

    permission_modules = (
        _build_permission_modules(
            permissions=managed_permissions,
            direct_permission_ids=(
                direct_permission_ids
            ),
            group_permission_ids=(
                group_permission_ids
            ),
        )
    )

    managed_direct_ids = (
        direct_permission_ids
        & managed_permission_ids
    )
    managed_group_ids = (
        group_permission_ids
        & managed_permission_ids
    )
    managed_effective_ids = (
        managed_direct_ids
        | managed_group_ids
    )

    assignments = list(
        _active_assignments_queryset().filter(
            user=target_user,
        )
    )

    role_preset_options = (
        _build_role_preset_options(
            permissions=managed_permissions,
        )
    )

    context = {
        "target_user": target_user,
        "role_choices": User.Roles.choices,
        "role_preset_options": (
            role_preset_options
        ),
        "permission_actions": (
            PERMISSION_ACTIONS
        ),
        "permission_modules": (
            permission_modules
        ),
        "assignments": assignments,
        "groups": target_user.groups.all().order_by(
            "name",
            "pk",
        ),
        "permission_summary": {
            "available": len(
                managed_permission_ids
            ),
            "direct": len(
                managed_direct_ids
            ),
            "inherited": len(
                managed_group_ids
            ),
            "effective": len(
                managed_effective_ids
            ),
        },
    }

    return render(
        request,
        "accounts/permissions/user_edit.html",
        context,
    )