# accounts/admin.py
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.utils.translation import gettext_lazy as _

from django.contrib.auth.models import Permission  # <- مهم لنسجّل PermissionAdmin
from .models import User


# --------------------------
# Permission admin (لأجل autocomplete على user_permissions)
# --------------------------
@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    search_fields = ("name", "codename", "content_type__app_label", "content_type__model")
    list_display = ("id", "name", "codename", "content_type")
    list_per_page = 50


# --------------------------
# Forms
# --------------------------
class UserAdminCreationForm(forms.ModelForm):
    """
    Form used in the Django Admin 'Add user' page.
    Handles password confirmation + sets password hash.
    (لا نفرض تغيير الدور إذا تم اختيار superuser)
    """
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Confirm Password"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = (
            "email",
            "username",
            "role",
            "is_approved",
            "is_staff",
            "is_superuser",
            "is_active",
        )

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("The two password fields didn’t match."))
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])

        # اتساق أساسي:
        # superuser ⇒ staff + approved
        if user.is_superuser:
            user.is_staff = True
            user.is_approved = True

        # role=admin ⇒ امنحيه staff (بدون إجبار superuser)
        if user.role == "admin":
            user.is_staff = True

        if commit:
            user.save()
        return user


class UserAdminChangeForm(forms.ModelForm):
    """
    Form used in the Django Admin 'Change user' page.
    Shows hashed password read-only.
    """
    password = ReadOnlyPasswordHashField(
        label=_("Password"),
        help_text=_(
            "Raw passwords are not stored, so there is no way to see "
            "this user’s password. You can change the password using "
            "the 'Change password' form."
        ),
    )

    class Meta:
        model = User
        fields = (
            "email",
            "username",
            "password",
            "role",
            "is_approved",
            "is_staff",
            "is_superuser",
            "is_active",
            "groups",
            "user_permissions",
        )

    def clean_password(self):
        # لا نغيّر الهش القديم؛ نعرضه للقراءة فقط
        return self.initial.get("password")


# --------------------------
# Admin registration
# --------------------------
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin interface for the custom User model.
    Email is the primary identifier; role + approval controlled here.
    فصل الدور الوظيفي عن الامتياز التقني (superuser).
    """
    model = User
    add_form = UserAdminCreationForm
    form = UserAdminChangeForm

    # ---- Helpers ----
    def display_role(self, obj):
        base = obj.role or "-"
        return f"{base} (SUPER)" if obj.is_superuser else base

    display_role.short_description = _("Role")

    # ---- List view ----
    list_display = (
        "email",
        "username",
        "display_role",
        "is_approved",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    list_filter = ("role", "is_approved", "is_staff", "is_superuser", "is_active")
    list_editable = ("is_approved",)
    list_display_links = ("email",)

    # مهم: في Django الـ search_fields تستخدم icontains افتراضياً،
    # لذلك لا نكتب __icontains هنا.
    search_fields = ("email", "username", "role")
    ordering = ("email",)
    list_per_page = 50

    # يوفّر اختيارًا أسرع للمجموعات والصلاحيات
    autocomplete_fields = ("groups", "user_permissions")

    # لا نكرر filter_horizontal لنفس الحقول مع autocomplete لتجنب تعارض الواجهات
    # filter_horizontal = ("groups", "user_permissions")

    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        (_("Role & Approval"), {"fields": ("role", "is_approved")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_staff",
                    "is_active",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Important Dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "role",
                    "is_approved",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                    "is_active",
                ),
            },
        ),
    )

    # ---- Actions ----
    @admin.action(description=_("Approve selected users"))
    def mark_approved(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, _("%d user(s) approved.") % updated)

    @admin.action(description=_("Unapprove selected users"))
    def mark_unapproved(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, _("%d user(s) unapproved.") % updated)

    actions = ("mark_approved", "mark_unapproved")

    # ---- Restrict sensitive flags for non-superusers ----
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if not request.user.is_superuser:
            # منع ترقية الذات أو العبث بالدور/الصلاحيات الحساسة
            ro += ["is_superuser", "role", "groups", "user_permissions", "is_staff"]
        return ro

    def save_model(self, request, obj, form, change):
        """
        اتساق الصلاحيات عند الحفظ:
        - إذا superuser ⇒ staff + approved
        - إذا role=admin ⇒ staff (بدون إجبار superuser)
        (لا نغير الدور تلقائياً عند تفعيل superuser)
        """
        if obj.is_superuser:
            obj.is_staff = True
            obj.is_approved = True
        if obj.role == "admin":
            obj.is_staff = True
        super().save_model(request, obj, form, change)
