# lab/admin.py
from django import forms
from django.contrib import admin
from .models import LabOrder, LabResult


class ClinicalFileInput(forms.FileInput):
    """Admin widget that avoids rendering direct MEDIA_URL links for clinical files."""


class LabOrderAdminForm(forms.ModelForm):
    class Meta:
        model = LabOrder
        fields = "__all__"
        widgets = {
            "doctor_attachment": ClinicalFileInput,
        }


class LabResultAdminForm(forms.ModelForm):
    class Meta:
        model = LabResult
        fields = "__all__"
        widgets = {
            "attachment": ClinicalFileInput,
        }


class LabResultInline(admin.StackedInline):
    model = LabResult
    form = LabResultAdminForm
    extra = 0
    can_delete = False


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    form = LabOrderAdminForm
    list_display = ("id", "patient", "doctor", "status", "urgency", "created_at")
    list_filter = ("status", "urgency", "created_at")
    search_fields = ("patient__full_name", "doctor__user__username", "requested_tests_text")
    inlines = [LabResultInline]


@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    form = LabResultAdminForm
    list_display = ("id", "order", "status", "verified_by", "verified_at", "updated_at")
    list_filter = ("status", "verified_at")
