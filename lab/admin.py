# lab/admin.py
from django.contrib import admin
from .models import LabOrder, LabResult


class LabResultInline(admin.StackedInline):
    model = LabResult
    extra = 0
    can_delete = False


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "status", "urgency", "created_at")
    list_filter = ("status", "urgency", "created_at")
    search_fields = ("patient__full_name", "doctor__user__username", "requested_tests_text")
    inlines = [LabResultInline]


@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "verified_by", "verified_at", "updated_at")
    list_filter = ("status", "verified_at")
