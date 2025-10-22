# prescription/admin.py

from django.contrib import admin
from django.utils.html import format_html

from .models import Prescription, Medication

class MedicationInline(admin.TabularInline):
    model = Medication
    extra = 1
    verbose_name = "Medication"
    verbose_name_plural = "Medications"
    fields = ("name", "dosage")
    # إذا أردت منع الحذف من أجل الأرشفة الصارم:
    # can_delete = False

@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient_full_name",
        "doctor",
        "appointment",
        "date_issued",
        "medications_list",
        "qr_code_preview",
    )
    list_select_related = ("doctor", "appointment")
    search_fields = (
        "patient_full_name",
        "doctor__user__username",
        "medications__name",
    )
    list_filter = ("doctor", "date_issued")
    date_hierarchy = "date_issued"
    readonly_fields = ("date_issued", "qr_code_preview")
    inlines = [MedicationInline]

    def medications_list(self, obj):
        """عرض أسماء الأدوية مفصولة بفواصل"""
        meds = obj.medications.all().values_list("name", flat=True)
        return ", ".join(meds) or "-"
    medications_list.short_description = "Medications"

    def qr_code_preview(self, obj):
        """عرض صورة الـ QR code بحجم صغير"""
        if obj.qr_code:
            return format_html(
                '<img src="{}" width="80" height="80" style="object-fit:contain;"/>',
                obj.qr_code.url,
            )
        return "-"
    qr_code_preview.short_description = "QR Code"
