from django.contrib import admin
from django.utils.html import format_html
from .models import Doctor

@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    """
    Custom admin for managing Doctor profiles with advanced UI features.
    """

    list_display = (
        "photo_thumb",
        "full_name",
        "specialty",
        "user_email",
        "consultation_fee",
        "experience_years",
        "phone",
        "available",
        "rating",
    )
    list_display_links = ("full_name",)
    list_select_related = ("user",)
    list_filter = ("available", "specialty", "gender")
    search_fields = ("full_name", "specialty", "phone", "user__email", "user__username")
    ordering = ("full_name",)
    list_per_page = 25
    date_hierarchy = "created_at"
    empty_value_display = "-"

    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)

    fieldsets = (
        (
            "User & Identity",
            {
                "fields": (
                    "user",
                    "full_name",
                    "specialty",
                ),
            },
        ),
        (
            "Contact Information",
            {
                "fields": (
                    "phone",
                    "clinic_address",
                    "photo",
                ),
            },
        ),
        (
            "Professional Details",
            {
                "fields": (
                    "short_bio",
                    "available",
                    "consultation_fee",
                    "experience_years",
                    "rating",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="User Email", ordering="user__email")
    def user_email(self, obj):
        return obj.user.email or self.empty_value_display

    @admin.display(description="Photo")
    def photo_thumb(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" width="40" style="border-radius:50%;" alt="{}" title="{}" />',
                obj.photo.url,
                obj.full_name or obj.user.get_full_name() or "",
                obj.full_name or obj.user.get_full_name() or "",
            )
        return self.empty_value_display

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj:
            ro.append("user")
        return ro
