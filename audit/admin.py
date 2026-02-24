# audit/admin.py
from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "app_label",
        "model_name",
        "object_id",
        "ip_address",
    )
    list_filter = ("action", "app_label", "model_name", "created_at")
    search_fields = ("actor__username", "message", "object_repr", "object_id", "path")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False  # logs should not be added manually

    def has_change_permission(self, request, obj=None):
        return False  # logs should not be edited