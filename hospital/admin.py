from django.contrib import admin

from .models import Branch, Department, Hospital, StaffAssignment


@admin.register(Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "phone", "is_active", "created_at")
    search_fields = ("name", "code", "phone", "email")
    list_filter = ("is_active",)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "hospital", "phone", "is_active")
    search_fields = ("name", "code", "hospital__name")
    list_filter = ("hospital", "is_active")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "branch",
        "phone_extension",
        "is_active",
    )
    search_fields = (
        "name",
        "code",
        "branch__name",
        "branch__hospital__name",
    )
    list_filter = ("branch__hospital", "branch", "is_active")


@admin.register(StaffAssignment)
class StaffAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "role",
        "hospital",
        "branch",
        "department",
        "is_primary",
        "is_active",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "hospital__name",
        "branch__name",
        "department__name",
    )

    list_filter = (
        "role",
        "hospital",
        "branch",
        "department",
        "is_primary",
        "is_active",
    )