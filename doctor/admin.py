# doctor/admin.py
from __future__ import annotations

from django import forms
from django.contrib import admin
from django.utils.html import format_html, format_html_join
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from doctor.models import Doctor

# Optional: register Specialty if it exists (won't break if you remove it later)
try:
    from doctor.models import Specialty  # type: ignore
except Exception:  # pragma: no cover
    Specialty = None  # type: ignore


def _has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _unique_code(model, base: str, pk=None) -> str:
    """
    Make a unique slug/code for model.code.
    """
    base = (base or "").strip()
    if not base:
        base = "specialty"

    code = base
    i = 2
    qs = model.objects.all()
    if pk:
        qs = qs.exclude(pk=pk)

    while qs.filter(code=code).exists():
        code = f"{base}-{i}"
        i += 1
    return code


def _hex_to_rgb(hex_color: str):
    """
    '#RRGGBB' -> (r,g,b) or None
    """
    try:
        s = (hex_color or "").strip()
        if not s.startswith("#") or len(s) != 7:
            return None
        r = int(s[1:3], 16)
        g = int(s[3:5], 16)
        b = int(s[5:7], 16)
        return (r, g, b)
    except Exception:
        return None


def _is_light(hex_color: str) -> bool:
    """
    True if color is perceptually light.
    """
    rgb = _hex_to_rgb(hex_color)
    if not rgb:
        return True
    r, g, b = rgb
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return lum >= 160


def _auto_text_color(bg_hex: str) -> str:
    """
    Choose black/white based on background.
    """
    return "#111827" if _is_light(bg_hex) else "#ffffff"


# =========================
# Specialty Admin (Optional)
# =========================
if Specialty is not None:

    class SpecialtyAdminForm(forms.ModelForm):
        """
        Auto-generate `code` from `name` if user leaves it empty.
        Supports Arabic by allow_unicode=True.
        Ensures uniqueness by adding -2, -3, ...
        """

        class Meta:
            model = Specialty
            fields = "__all__"

        def clean(self):
            cleaned = super().clean()

            name = (cleaned.get("name") or "").strip()
            code = (cleaned.get("code") or "").strip()

            if not code and name:
                code = slugify(name, allow_unicode=True)

            if not code:
                code = "specialty"

            cleaned["code"] = _unique_code(Specialty, code, pk=getattr(self.instance, "pk", None))
            return cleaned

    @admin.register(Specialty)
    class SpecialtyAdmin(admin.ModelAdmin):
        """
        ✅ يدعم is_public (إذا موجود) حتى تختارين الاختصاصات الظاهرة للعلن.
        """
        form = SpecialtyAdminForm
        list_per_page = 25
        ordering = ("name",)

        search_fields = ("name", "code")

        def get_list_display(self, request):
            cols = ["name"]
            if _has_field(Specialty, "is_public"):
                cols.append("is_public")
            cols.append("code")

            if _has_field(Specialty, "primary_color"):
                cols.append("primary_color")
            if _has_field(Specialty, "accent_color"):
                cols.append("accent_color")
            if _has_field(Specialty, "icon"):
                cols.append("icon_preview")
            return tuple(cols)

        def get_list_filter(self, request):
            flt = []
            if _has_field(Specialty, "is_public"):
                flt.append("is_public")
            return tuple(flt)

        def get_list_display_links(self, request, list_display):
            # نخلي الاسم هو الرابط حتى (is_public) يصير قابل للتعديل من الجدول
            return ("name",)

        def get_list_editable(self, request):
            # ✅ toggle سريع من جدول الاختصاصات
            if _has_field(Specialty, "is_public"):
                return ("is_public",)
            return ()

        def get_readonly_fields(self, request, obj=None):
            ro = []
            if _has_field(Specialty, "icon"):
                ro.append("icon_preview")
            for f in ("created_at", "updated_at"):
                if _has_field(Specialty, f):
                    ro.append(f)
            return tuple(ro)

        def get_fieldsets(self, request, obj=None):
            specialty_fields = [f for f in ("name", "code") if _has_field(Specialty, f)]
            if _has_field(Specialty, "is_public"):
                # نخليه ضمن نفس مجموعة Specialty
                specialty_fields.append("is_public")

            branding_fields = []
            for f in ("icon", "primary_color", "accent_color"):
                if _has_field(Specialty, f):
                    branding_fields.append(f)
            if "icon" in branding_fields:
                branding_fields.insert(branding_fields.index("icon") + 1, "icon_preview")

            timestamps = [f for f in ("created_at", "updated_at") if _has_field(Specialty, f)]

            sets = []
            if specialty_fields:
                sets.append((_("Specialty"), {"fields": tuple(specialty_fields)}))
            if branding_fields:
                sets.append((_("Branding"), {"fields": tuple(branding_fields)}))
            if timestamps:
                sets.append((_("Timestamps"), {"fields": tuple(timestamps), "classes": ("collapse",)}))
            return tuple(sets)

        @admin.display(description=_("Icon Preview"))
        def icon_preview(self, obj):
            f = getattr(obj, "icon", None)
            if f and getattr(f, "url", None):
                return format_html(
                    '<img src="{}" style="max-height:60px;max-width:120px;'
                    'border:1px solid #e5e7eb;border-radius:10px;padding:4px;background:#fff;" />',
                    f.url,
                )
            return "-"


# =========================
# Doctor Admin
# =========================
@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    """
    Admin for managing Doctor profiles.

    ✅ Includes:
    - Avatar photo (photo)
    - Card cover photo (cover_photo)
    - Prescription theme controls + previews
    - Branding thumbs + watermark preview
    """

    list_per_page = 25
    empty_value_display = "-"

    # ✅ REQUIRED (for Django autocomplete system check)
    search_fields = ("user__username", "user__email")

    class Media:
        css = {"all": ("admin/css/clinichub_admin_rtl.css",)}

    # -----------------------------
    # Queryset optimisations (safe)
    # -----------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("user")
        if _has_field(Doctor, "specialty_profile"):
            qs = qs.select_related("specialty_profile")
        return qs

    # Autocomplete (dynamic)
    def get_autocomplete_fields(self, request):
        fields = ["user"]
        if _has_field(Doctor, "specialty_profile"):
            fields.append("specialty_profile")
        return tuple(fields)

    # Date hierarchy (safe)
    def get_date_hierarchy(self, request):
        return "created_at" if _has_field(Doctor, "created_at") else None

    # Readonly (safe)
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))

        for f in ("created_at", "updated_at"):
            if _has_field(Doctor, f) and f not in ro:
                ro.append(f)

        # previews
        for f in ("photo_preview", "cover_preview", "watermark_preview", "theme_preview"):
            if f not in ro:
                ro.append(f)

        # lock user on edit
        if obj and "user" not in ro:
            ro.append("user")

        return tuple(ro)

    # List display
    def get_list_display(self, request):
        cols = []

        if _has_field(Doctor, "cover_photo"):
            cols.append("cover_thumb")

        cols.append("photo_thumb")

        if _has_field(Doctor, "full_name"):
            cols.append("full_name")
        else:
            cols.append("user_email")

        if _has_field(Doctor, "entity_type"):
            cols.append("entity_type_value")

        cols.append("specialty_badge")

        if (
            _has_field(Doctor, "prescription_header_bg")
            or _has_field(Doctor, "prescription_paper_bg")
            or _has_field(Doctor, "prescription_header_text_color")
        ):
            cols.append("theme_badges")

        cols += [
            "syndicate_no",
            "syndicate_date",
            "user_email",
            "phone_value",
            "available_value",
            "rating_value",
            "consultation_fee_value",
            "experience_years_value",
            "branding_thumbs",
        ]
        return tuple(cols)

    def get_list_display_links(self, request, list_display):
        # ✅ آمن حتى لو تغيّر/اختفى full_name
        if "full_name" in list_display:
            return ("full_name",)
        return ("user_email",)

    # Search (dynamic & safe)
    def get_search_fields(self, request):
        fields = ["user__username", "user__email", "user__first_name", "user__last_name"]

        if _has_field(Doctor, "full_name"):
            fields.insert(0, "full_name")
        if _has_field(Doctor, "specialty"):
            fields.append("specialty")
        if _has_field(Doctor, "phone"):
            fields.append("phone")
        if _has_field(Doctor, "syndicate_registration_no"):
            fields.append("syndicate_registration_no")
        if _has_field(Doctor, "specialty_profile"):
            fields.append("specialty_profile__name")
            fields.append("specialty_profile__code")

        return tuple(fields)

    # Ordering (safe)
    def get_ordering(self, request):
        if _has_field(Doctor, "full_name"):
            return ("full_name",)
        return ("user__first_name", "user__last_name")

    # Filters (dynamic)
    def get_list_filter(self, request):
        base = []
        if _has_field(Doctor, "entity_type"):
            base.append("entity_type")

        for f in ("available", "gender", "specialty", "specialty_profile", "syndicate_registration_date"):
            if _has_field(Doctor, f):
                base.append(f)

        return tuple(base)

    # Fieldsets (dynamic & safe)
    def get_fieldsets(self, request, obj=None):
        identity_fields = ["user"]

        if _has_field(Doctor, "entity_type"):
            identity_fields.append("entity_type")

        if _has_field(Doctor, "full_name"):
            identity_fields.append("full_name")

        if _has_field(Doctor, "specialty_profile"):
            identity_fields.append("specialty_profile")
        if _has_field(Doctor, "specialty"):
            identity_fields.append("specialty")

        if _has_field(Doctor, "gender"):
            identity_fields.append("gender")

        fieldsets = [(_("User & Identity"), {"fields": tuple(identity_fields)})]

        # ✅ Contact + Images (Avatar/Cover)
        contact_fields = []
        for f in ("phone", "clinic_address", "photo"):
            if _has_field(Doctor, f):
                contact_fields.append(f)

        if "photo" in contact_fields:
            contact_fields.insert(contact_fields.index("photo") + 1, "photo_preview")

        if _has_field(Doctor, "cover_photo"):
            contact_fields.append("cover_photo")
            contact_fields.append("cover_preview")

        if contact_fields:
            fieldsets.append((_("Contact & Card Images"), {"fields": tuple(contact_fields)}))

        syndicate_fields = [
            f for f in ("syndicate_registration_no", "syndicate_registration_date") if _has_field(Doctor, f)
        ]
        if syndicate_fields:
            fieldsets.append(
                (
                    _("Syndicate / Union"),
                    {
                        "fields": tuple(syndicate_fields),
                        "description": _(
                            "These fields can be shown in prescription headers if you choose to render them."
                        ),
                    },
                )
            )

        # Theme colors for prescription + preview
        theme_fields = []
        for f in (
            "primary_color",
            "accent_color",
            "prescription_paper_bg",
            "prescription_paper_border",
            "prescription_header_bg",
            "prescription_header_text_color",
            "prescription_header_line_color",
            "prescription_specialty_text_color",
            "prescription_patient_label_color",
            "prescription_patient_value_color",
        ):
            if _has_field(Doctor, f):
                theme_fields.append(f)

        if theme_fields:
            theme_fields.append("theme_preview")
            fieldsets.append(
                (
                    _("Prescription Theme Colors"),
                    {
                        "fields": tuple(theme_fields),
                        "description": _(
                            "Set HEX colors per doctor for prescription paper/header + header line/specialty text + patient info colors."
                        ),
                    },
                )
            )

        branding_fields = []
        for f in ("clinic_logo", "signature_image", "prescription_header_illustration", "prescription_watermark"):
            if _has_field(Doctor, f):
                branding_fields.append(f)

        if "prescription_watermark" in branding_fields:
            branding_fields.insert(branding_fields.index("prescription_watermark") + 1, "watermark_preview")

        if branding_fields:
            fieldsets.append(
                (
                    _("Branding & Prescription Assets"),
                    {
                        "fields": tuple(branding_fields),
                        "description": _("These fields control prescription branding (logo/signature/header/watermark)."),
                    },
                )
            )

        prof_fields = [
            f for f in ("short_bio", "available", "consultation_fee", "experience_years", "rating")
            if _has_field(Doctor, f)
        ]
        if prof_fields:
            fieldsets.append((_("Professional Details"), {"fields": tuple(prof_fields)}))

        timestamps = [f for f in ("created_at", "updated_at") if _has_field(Doctor, f)]
        if timestamps:
            fieldsets.append((_("Timestamps"), {"fields": tuple(timestamps), "classes": ("collapse",)}))

        return tuple(fieldsets)

    # -----------------------------
    # Columns / Display helpers
    # -----------------------------
    @admin.display(description=_("Type"))
    def entity_type_value(self, obj: Doctor):
        try:
            if hasattr(obj, "get_entity_type_display"):
                return obj.get_entity_type_display() or self.empty_value_display
        except Exception:
            pass
        return getattr(obj, "entity_type", "") or self.empty_value_display

    @admin.display(description=_("User Email"), ordering="user__email")
    def user_email(self, obj: Doctor):
        return getattr(obj.user, "email", "") or self.empty_value_display

    @admin.display(description=_("Phone"))
    def phone_value(self, obj: Doctor):
        if _has_field(Doctor, "phone"):
            v = getattr(obj, "phone", "") or ""
            return v.strip() or self.empty_value_display
        return self.empty_value_display

    @admin.display(description=_("Available"))
    def available_value(self, obj: Doctor):
        if _has_field(Doctor, "available"):
            return "✅" if getattr(obj, "available", False) else "—"
        return self.empty_value_display

    @admin.display(description=_("Rating"))
    def rating_value(self, obj: Doctor):
        if _has_field(Doctor, "rating"):
            v = getattr(obj, "rating", None)
            return v if v is not None else self.empty_value_display
        return self.empty_value_display

    @admin.display(description=_("Fee"))
    def consultation_fee_value(self, obj: Doctor):
        if _has_field(Doctor, "consultation_fee"):
            v = getattr(obj, "consultation_fee", None)
            return v if v is not None else self.empty_value_display
        return self.empty_value_display

    @admin.display(description=_("Experience (Years)"))
    def experience_years_value(self, obj: Doctor):
        if _has_field(Doctor, "experience_years"):
            v = getattr(obj, "experience_years", None)
            return v if v is not None else self.empty_value_display
        return self.empty_value_display

    @admin.display(description=_("Syndicate No."))
    def syndicate_no(self, obj: Doctor):
        if _has_field(Doctor, "syndicate_registration_no"):
            val = getattr(obj, "syndicate_registration_no", "") or ""
            return val.strip() or self.empty_value_display
        return self.empty_value_display

    @admin.display(description=_("Syndicate Date"))
    def syndicate_date(self, obj: Doctor):
        if _has_field(Doctor, "syndicate_registration_date"):
            d = getattr(obj, "syndicate_registration_date", None)
            if d:
                return d.strftime("%d/%m/%Y")
        return self.empty_value_display

    @admin.display(description=_("Avatar"))
    def photo_thumb(self, obj: Doctor):
        try:
            photo = getattr(obj, "photo", None)
            if photo and getattr(photo, "url", None):
                title = getattr(obj, "full_name", "") or obj.user.get_full_name() or ""
                return format_html(
                    '<img src="{}" width="40" height="40" '
                    'style="border-radius:50%;object-fit:cover;border:1px solid #e5e7eb;background:#fff;" '
                    'alt="{}" title="{}" />',
                    photo.url,
                    title,
                    title,
                )
        except Exception:
            pass
        return self.empty_value_display

    @admin.display(description=_("Cover"))
    def cover_thumb(self, obj: Doctor):
        """
        Wide cover thumb for the doctor card header image.
        """
        if not _has_field(Doctor, "cover_photo"):
            return self.empty_value_display
        try:
            cover = getattr(obj, "cover_photo", None)
            if cover and getattr(cover, "url", None):
                title = getattr(obj, "full_name", "") or obj.user.get_full_name() or ""
                return format_html(
                    '<img src="{}" width="84" height="42" '
                    'style="border-radius:10px;object-fit:cover;border:1px solid #e5e7eb;background:#fff;" '
                    'alt="{}" title="{}" />',
                    cover.url,
                    title,
                    title,
                )
        except Exception:
            pass
        return self.empty_value_display

    @admin.display(description=_("Avatar Preview"))
    def photo_preview(self, obj: Doctor):
        """
        Bigger preview on the edit page.
        """
        try:
            photo = getattr(obj, "photo", None)
            if photo and getattr(photo, "url", None):
                return format_html(
                    '<img src="{}" style="width:96px;height:96px;border-radius:18px;object-fit:cover;'
                    'border:1px solid #e5e7eb;background:#fff;box-shadow:0 10px 20px rgba(2,6,23,.08);" />',
                    photo.url,
                )
        except Exception:
            pass
        return self.empty_value_display

    @admin.display(description=_("Cover Preview"))
    def cover_preview(self, obj: Doctor):
        """
        Cover preview on the edit page.
        """
        if not _has_field(Doctor, "cover_photo"):
            return self.empty_value_display
        try:
            cover = getattr(obj, "cover_photo", None)
            if cover and getattr(cover, "url", None):
                return format_html(
                    '<img src="{}" style="width:320px;max-width:100%;height:110px;border-radius:16px;'
                    'object-fit:cover;border:1px solid #e5e7eb;background:#fff;'
                    'box-shadow:0 10px 22px rgba(2,6,23,.08);" />',
                    cover.url,
                )
        except Exception:
            pass
        return self.empty_value_display

    @admin.display(description=_("Specialty"))
    def specialty_badge(self, obj: Doctor):
        name = ""
        try:
            if hasattr(obj, "specialty_name"):
                name = (obj.specialty_name or "").strip()
        except Exception:
            name = ""

        if not name and _has_field(Doctor, "specialty_profile"):
            try:
                sp = getattr(obj, "specialty_profile", None)
                if sp:
                    name = (getattr(sp, "name", "") or "").strip()
            except Exception:
                name = ""

        if not name and _has_field(Doctor, "specialty"):
            name = (getattr(obj, "specialty", "") or "").strip()

        if not name:
            name = "General"

        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            'border:1px solid #e5e7eb;background:#fff;">{}</span>',
            name,
        )

    def _thumb(self, filefield, title: str, size: int = 42) -> str:
        try:
            if filefield and getattr(filefield, "url", None):
                return format_html(
                    '<img src="{}" width="{}" height="{}" '
                    'style="border-radius:10px;object-fit:cover;border:1px solid #e5e7eb;background:#fff;" '
                    'alt="{}" title="{}" />',
                    filefield.url,
                    size,
                    size,
                    title,
                    title,
                )
        except Exception:
            return ""
        return ""

    # Theme badges in list view
    @admin.display(description=_("Theme"))
    def theme_badges(self, obj: Doctor):
        def _val(field: str) -> str:
            return (getattr(obj, field, "") or "").strip()

        header_bg = _val("prescription_header_bg") if _has_field(Doctor, "prescription_header_bg") else ""
        paper_bg = _val("prescription_paper_bg") if _has_field(Doctor, "prescription_paper_bg") else ""
        header_tx = _val("prescription_header_text_color") if _has_field(Doctor, "prescription_header_text_color") else ""
        header_ln = _val("prescription_header_line_color") if _has_field(Doctor, "prescription_header_line_color") else ""
        spec_tx = _val("prescription_specialty_text_color") if _has_field(Doctor, "prescription_specialty_text_color") else ""

        chips = []
        if header_bg:
            chips.append(
                format_html(
                    '<span style="display:inline-flex;align-items:center;gap:6px;'
                    'padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#fff;">'
                    '<span style="width:10px;height:10px;border-radius:50%;background:{};border:1px solid #e5e7eb;"></span>'
                    '<span style="color:#334155;font-weight:800;">H</span></span>',
                    header_bg,
                )
            )
        if paper_bg:
            chips.append(
                format_html(
                    '<span style="display:inline-flex;align-items:center;gap:6px;'
                    'padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#fff;">'
                    '<span style="width:10px;height:10px;border-radius:50%;background:{};border:1px solid #e5e7eb;"></span>'
                    '<span style="color:#334155;font-weight:800;">P</span></span>',
                    paper_bg,
                )
            )
        if header_tx:
            chips.append(
                format_html(
                    '<span style="display:inline-flex;align-items:center;gap:6px;'
                    'padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#fff;">'
                    '<span style="width:10px;height:10px;border-radius:50%;background:{};border:1px solid #e5e7eb;"></span>'
                    '<span style="color:#334155;font-weight:800;">T</span></span>',
                    header_tx,
                )
            )
        if header_ln:
            chips.append(
                format_html(
                    '<span style="display:inline-flex;align-items:center;gap:6px;'
                    'padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#fff;">'
                    '<span style="width:10px;height:10px;border-radius:50%;background:{};border:1px solid #e5e7eb;"></span>'
                    '<span style="color:#334155;font-weight:800;">L</span></span>',
                    header_ln,
                )
            )
        if spec_tx:
            chips.append(
                format_html(
                    '<span style="display:inline-flex;align-items:center;gap:6px;'
                    'padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#fff;">'
                    '<span style="width:10px;height:10px;border-radius:50%;background:{};border:1px solid #e5e7eb;"></span>'
                    '<span style="color:#334155;font-weight:800;">S</span></span>',
                    spec_tx,
                )
            )

        if not chips:
            return self.empty_value_display

        return format_html(
            '<div style="display:flex;gap:6px;flex-wrap:wrap;">{}</div>',
            format_html_join("", "{}", ((c,) for c in chips)),
        )

    @admin.display(description=_("Theme Preview"))
    def theme_preview(self, obj: Doctor):
        """
        Preview card: paper + header + header text + line + specialty + patient colors.
        """
        paper_bg = (getattr(obj, "prescription_paper_bg", "") or "").strip() or "#FFFFFF"
        border = (getattr(obj, "prescription_paper_border", "") or "").strip() or "#E9ECEF"

        primary = (getattr(obj, "primary_color", "") or "").strip() or "#0b4ea2"
        accent = (getattr(obj, "accent_color", "") or "").strip() or "#0d9488"

        header_bg = (getattr(obj, "prescription_header_bg", "") or "").strip() or primary

        header_tx = (getattr(obj, "prescription_header_text_color", "") or "").strip()
        if not header_tx:
            header_tx = _auto_text_color(header_bg)

        header_ln = (getattr(obj, "prescription_header_line_color", "") or "").strip() or accent

        spec_tx = (getattr(obj, "prescription_specialty_text_color", "") or "").strip()
        if not spec_tx:
            spec_tx = "#334155" if _is_light(header_bg) else "rgba(255,255,255,.90)"

        plabel = (getattr(obj, "prescription_patient_label_color", "") or "").strip() or "#64748b"
        pvalue = (getattr(obj, "prescription_patient_value_color", "") or "").strip() or "#0f172a"

        name = (
            getattr(obj, "full_name", "")
            or obj.user.get_full_name()
            or getattr(obj.user, "username", "")
            or "Doctor"
        )

        return format_html(
            '<div style="width:300px;border:1px solid {};border-radius:14px;overflow:hidden;background:{};">'
            '<div style="padding:12px 12px;background:{};color:{};font-weight:900;text-align:center;">{}</div>'
            '<div style="height:4px;background:linear-gradient(90deg, rgba(0,0,0,0), {}, rgba(0,0,0,0));"></div>'
            '<div style="padding:10px 12px;text-align:center;color:{};font-weight:800;">اختصاص الجلدية والحساسية والليزر</div>'
            '<div style="padding:10px 12px;">'
            '<div style="display:flex;gap:16px;flex-wrap:wrap;">'
            '<div>'
            '<div style="font-size:11px;color:{};font-weight:800;">الاسم</div>'
            '<div style="font-size:13px;color:{};font-weight:900;">محمد</div>'
            "</div>"
            "<div>"
            '<div style="font-size:11px;color:{};font-weight:800;">العمر</div>'
            '<div style="font-size:13px;color:{};font-weight:900;">28</div>'
            "</div>"
            "<div>"
            '<div style="font-size:11px;color:{};font-weight:800;">الجنس</div>'
            '<div style="font-size:13px;color:{};font-weight:900;">ذكر</div>'
            "</div>"
            "</div>"
            '<div style="margin-top:10px;color:#64748b;font-size:12px;">'
            "paper: {} • header: {} • text: {}"
            "</div>"
            "</div>"
            "</div>",
            border,
            paper_bg,
            header_bg,
            header_tx,
            name,
            header_ln,
            spec_tx,
            plabel,
            pvalue,
            plabel,
            pvalue,
            plabel,
            pvalue,
            paper_bg,
            header_bg,
            header_tx,
        )

    @admin.display(description=_("Watermark Preview"))
    def watermark_preview(self, obj: Doctor):
        try:
            if hasattr(obj, "get_prescription_watermark_asset"):
                wm = obj.get_prescription_watermark_asset()
            else:
                wm = getattr(obj, "prescription_watermark", None)

            if wm and getattr(wm, "url", None):
                return format_html(
                    '<div style="display:flex;align-items:center;gap:10px;">'
                    '<img src="{}" style="max-height:64px;max-width:140px;'
                    'border:1px solid #e5e7eb;border-radius:12px;padding:6px;background:#fff;" />'
                    '<span style="color:#64748b;font-weight:700;">(Used in prescription body as watermark)</span>'
                    "</div>",
                    wm.url,
                )
        except Exception:
            pass
        return self.empty_value_display

    @admin.display(description=_("Branding"))
    def branding_thumbs(self, obj: Doctor):
        parts = []

        clinic_logo = getattr(obj, "clinic_logo", None) if _has_field(Doctor, "clinic_logo") else None
        signature_image = getattr(obj, "signature_image", None) if _has_field(Doctor, "signature_image") else None
        header_art = (
            getattr(obj, "prescription_header_illustration", None)
            if _has_field(Doctor, "prescription_header_illustration")
            else None
        )
        watermark = getattr(obj, "prescription_watermark", None) if _has_field(Doctor, "prescription_watermark") else None

        if clinic_logo and getattr(clinic_logo, "url", None):
            parts.append(self._thumb(clinic_logo, "Clinic Logo"))
        if signature_image and getattr(signature_image, "url", None):
            parts.append(self._thumb(signature_image, "Signature"))
        if header_art and getattr(header_art, "url", None):
            parts.append(self._thumb(header_art, "Header Art"))
        if watermark and getattr(watermark, "url", None):
            parts.append(self._thumb(watermark, "Watermark"))

        # fallback watermark from specialty
        if not (watermark and getattr(watermark, "url", None)):
            try:
                if hasattr(obj, "get_prescription_watermark_asset"):
                    wm2 = obj.get_prescription_watermark_asset()
                    if wm2 and getattr(wm2, "url", None):
                        parts.append(self._thumb(wm2, "Watermark (Specialty)"))
            except Exception:
                pass

        if not parts:
            return self.empty_value_display

        return format_html(
            '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">{}</div>',
            format_html_join("", "{}", ((p,) for p in parts)),
        )
