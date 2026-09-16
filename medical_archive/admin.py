# File: medical_archive/admin.py
from __future__ import annotations

import os
import mimetypes

from django.contrib import admin
from django.db import transaction
from django.db.models import Count
from django.template.defaultfilters import filesizeformat
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import PatientArchive, ArchiveAttachment, ArchiveVoiceNote


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------
def _safe_file_url(f) -> str | None:
    try:
        return f.url
    except Exception:
        return None


def _safe_basename(name: str) -> str:
    return os.path.basename(name or "")


def _guess_mime_from_name(name: str) -> str | None:
    """
    Useful for <source type="..."> inside <audio>.
    """
    if not name:
        return None
    mime, _ = mimetypes.guess_type(name)
    return (mime or "").lower() or None


def _render_attachment_preview(obj: ArchiveAttachment, size: int = 80):
    """
    Preview rules:
    - If model provides preview_html() use it.
    - Else if image -> render img
    - Else if pdf -> render link
    """
    if not obj or not getattr(obj, "file", None) or not getattr(obj.file, "name", None):
        return "-"

    # Prefer model-provided preview_html if exists
    if hasattr(obj, "preview_html") and callable(getattr(obj, "preview_html")):
        try:
            return obj.preview_html()
        except Exception:
            pass

    name = (obj.file.name or "").lower()
    url = _safe_file_url(obj.file)
    if not url:
        return "-"

    # ✅ Add webp support
    if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return format_html(
            '<img src="{}" style="max-height:{}px;max-width:{}px;object-fit:cover;border-radius:8px;" loading="lazy" />',
            url,
            size,
            size,
        )

    if name.endswith(".pdf"):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, _("Open PDF"))

    return "-"


def _render_voice_player(obj: ArchiveVoiceNote, width_px: int = 240):
    if not obj or not getattr(obj, "audio", None) or not getattr(obj.audio, "name", None):
        return "-"

    url = _safe_file_url(obj.audio)
    if not url:
        return "-"

    mime = _guess_mime_from_name(obj.audio.name)

    # ✅ Add type attribute when possible (helps some browsers)
    if mime:
        return format_html(
            '<audio controls preload="metadata" style="width:{}px;">'
            '<source src="{}" type="{}">'
            "{}"
            "</audio>",
            width_px,
            url,
            mime,
            _("Your browser does not support the audio element."),
        )

    return format_html(
        '<audio controls preload="metadata" style="width:{}px;">'
        '<source src="{}">'
        "{}"
        "</audio>",
        width_px,
        url,
        _("Your browser does not support the audio element."),
    )


# ---------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------
class ArchiveAttachmentInline(admin.TabularInline):
    model = ArchiveAttachment
    extra = 1
    show_change_link = True
    can_delete = True

    fields = (
        "file",
        "file_link",
        "description",
        "uploaded_at",
        "uploaded_by",
        "file_size_display",
        "preview_display",
    )
    readonly_fields = (
        "file_link",
        "uploaded_at",
        "uploaded_by",
        "file_size_display",
        "preview_display",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("uploaded_by", "archive")

    @admin.display(description=_("File"))
    def file_link(self, obj: ArchiveAttachment):
        if not obj or not getattr(obj, "file", None) or not getattr(obj.file, "name", None):
            return "-"
        name = _safe_basename(obj.file.name)
        url = _safe_file_url(obj.file)
        if not url:
            return name
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, name)

    @admin.display(description=_("Size"))
    def file_size_display(self, obj: ArchiveAttachment) -> str:
        if not obj or not getattr(obj, "file", None):
            return "-"
        try:
            return filesizeformat(obj.file.size)
        except Exception:
            return "-"

    @admin.display(description=_("Preview"))
    def preview_display(self, obj: ArchiveAttachment):
        return _render_attachment_preview(obj, size=80)


class ArchiveVoiceNoteInline(admin.TabularInline):
    model = ArchiveVoiceNote
    extra = 0
    show_change_link = True
    can_delete = True

    fields = (
        "audio",
        "audio_link",
        "title",
        "duration_seconds",
        "recorded_at",
        "recorded_by",
        "audio_size_display",
        "player_preview",
    )
    readonly_fields = (
        "audio_link",
        "recorded_at",
        "recorded_by",
        "audio_size_display",
        "player_preview",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("recorded_by", "archive")

    @admin.display(description=_("Audio"))
    def audio_link(self, obj: ArchiveVoiceNote):
        if not obj or not getattr(obj, "audio", None) or not getattr(obj.audio, "name", None):
            return "-"
        name = _safe_basename(obj.audio.name)
        url = _safe_file_url(obj.audio)
        if not url:
            return name
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, name)

    @admin.display(description=_("Size"))
    def audio_size_display(self, obj: ArchiveVoiceNote) -> str:
        if not obj or not getattr(obj, "audio", None):
            return "-"
        try:
            return filesizeformat(obj.audio.size)
        except Exception:
            return "-"

    @admin.display(description=_("Player"))
    def player_preview(self, obj: ArchiveVoiceNote):
        return _render_voice_player(obj, width_px=240)


# ---------------------------------------------------------------------
# PatientArchive Admin
# ---------------------------------------------------------------------
@admin.register(PatientArchive)
class PatientArchiveAdmin(admin.ModelAdmin):
    inlines = [ArchiveAttachmentInline, ArchiveVoiceNoteInline]

    list_display = (
        "patient",
        "doctor",
        "title",
        "archive_type",
        "is_critical",
        "status",
        "attachments_count_display",
        "voice_count_display",
        "created_at",
        "created_by",
    )

    list_filter = (
        "archive_type",
        "is_critical",
        "status",
        "created_at",
        "doctor",
    )

    search_fields = (
        "title",
        "notes",
        "summary_report",
        "patient__full_name",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "doctor__user__username",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )

    date_hierarchy = "created_at"
    list_select_related = ("patient", "doctor", "doctor__user", "created_by", "updated_by")

    actions = (
        "mark_as_final",
        "mark_as_draft",
        "mark_as_cancelled",
        "set_critical",
        "unset_critical",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related("patient", "doctor", "doctor__user", "created_by", "updated_by")
        qs = qs.annotate(
            _attachments_count=Count("attachments", distinct=True),
            _voice_count=Count("voice_notes", distinct=True),
        )
        return qs

    @admin.display(description=_("Attachments"), ordering="_attachments_count")
    def attachments_count_display(self, obj: PatientArchive) -> int:
        return int(getattr(obj, "_attachments_count", 0) or 0)

    @admin.display(description=_("Voice"), ordering="_voice_count")
    def voice_count_display(self, obj: PatientArchive) -> int:
        return int(getattr(obj, "_voice_count", 0) or 0)

    def get_autocomplete_fields(self, request):
        """
        ✅ Safe autocomplete:
        Only include FK fields if the related model is registered AND has search_fields.
        This prevents admin crash (ImproperlyConfigured).
        """
        safe_fields = []
        for fname in ("patient", "doctor", "appointment", "prescription"):
            try:
                f = self.model._meta.get_field(fname)
            except Exception:
                continue

            rel_model = getattr(getattr(f, "remote_field", None), "model", None)
            if not rel_model:
                continue

            related_admin = self.admin_site._registry.get(rel_model)
            if related_admin and getattr(related_admin, "search_fields", None):
                safe_fields.append(fname)

        return tuple(safe_fields)

    def save_model(self, request, obj: PatientArchive, form, change: bool) -> None:
        if not change and not getattr(obj, "created_by_id", None):
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change) -> None:
        """
        Automatically set:
        - uploaded_by for attachments
        - recorded_by for voice notes
        """
        model = getattr(formset, "model", None)

        # Default behavior for other formsets
        if model not in (ArchiveAttachment, ArchiveVoiceNote):
            return super().save_formset(request, form, formset, change)

        with transaction.atomic():
            instances = formset.save(commit=False)

            for instance in instances:
                if model is ArchiveAttachment:
                    if not getattr(instance, "uploaded_by_id", None):
                        instance.uploaded_by = request.user

                if model is ArchiveVoiceNote:
                    if not getattr(instance, "recorded_by_id", None):
                        instance.recorded_by = request.user

                instance.save()

            for obj in getattr(formset, "deleted_objects", []):
                obj.delete()

            formset.save_m2m()

    # ---------------- Admin Actions ----------------
    @admin.action(description=_("Mark selected as Final"))
    def mark_as_final(self, request, queryset):
        queryset.update(status="final")

    @admin.action(description=_("Mark selected as Draft"))
    def mark_as_draft(self, request, queryset):
        queryset.update(status="draft")

    @admin.action(description=_("Mark selected as Cancelled"))
    def mark_as_cancelled(self, request, queryset):
        queryset.update(status="cancelled")

    @admin.action(description=_("Set Critical"))
    def set_critical(self, request, queryset):
        queryset.update(is_critical=True)

    @admin.action(description=_("Unset Critical"))
    def unset_critical(self, request, queryset):
        queryset.update(is_critical=False)


# ---------------------------------------------------------------------
# ArchiveAttachment Admin (standalone)
# ---------------------------------------------------------------------
@admin.register(ArchiveAttachment)
class ArchiveAttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "short_file_name",
        "archive",
        "file_type_display",
        "uploaded_at",
        "uploaded_by",
        "file_size_display",
        "preview_display",
    )
    list_filter = ("uploaded_at", "uploaded_by")
    search_fields = (
        "file",
        "description",
        "archive__title",
        "archive__patient__full_name",
        "archive__doctor__user__username",
        "archive__doctor__user__first_name",
        "archive__doctor__user__last_name",
    )
    readonly_fields = ("uploaded_at", "uploaded_by", "file_size_display", "preview_display")
    autocomplete_fields = ("archive",)
    list_select_related = ("archive", "archive__patient", "archive__doctor", "archive__doctor__user", "uploaded_by")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("archive", "archive__patient", "archive__doctor", "archive__doctor__user", "uploaded_by")

    @admin.display(description=_("File name"))
    def short_file_name(self, obj: ArchiveAttachment) -> str:
        if not obj or not getattr(obj, "file", None) or not getattr(obj.file, "name", None):
            return "-"
        return _safe_basename(obj.file.name)

    @admin.display(description=_("Type"))
    def file_type_display(self, obj: ArchiveAttachment) -> str:
        if not obj or not getattr(obj, "file", None) or not getattr(obj.file, "name", None):
            return "-"
        ext = os.path.splitext(obj.file.name)[1].lstrip(".").lower()
        return ext.upper() if ext else "-"

    @admin.display(description=_("Size"))
    def file_size_display(self, obj: ArchiveAttachment) -> str:
        if not obj or not getattr(obj, "file", None):
            return "-"
        try:
            return filesizeformat(obj.file.size)
        except Exception:
            return "-"

    @admin.display(description=_("Preview"))
    def preview_display(self, obj: ArchiveAttachment):
        return _render_attachment_preview(obj, size=110)

    def save_model(self, request, obj: ArchiveAttachment, form, change: bool) -> None:
        if not change and not getattr(obj, "uploaded_by_id", None):
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------
# ArchiveVoiceNote Admin (standalone)
# ---------------------------------------------------------------------
@admin.register(ArchiveVoiceNote)
class ArchiveVoiceNoteAdmin(admin.ModelAdmin):
    list_display = (
        "title_or_file",
        "archive",
        "recorded_at",
        "recorded_by",
        "duration_seconds",
        "audio_size_display",
        "player_preview",
    )
    list_filter = ("recorded_at", "recorded_by")
    search_fields = (
        "title",
        "audio",
        "archive__title",
        "archive__patient__full_name",
        "archive__doctor__user__username",
    )
    readonly_fields = ("recorded_at", "recorded_by", "audio_size_display", "player_preview")
    autocomplete_fields = ("archive",)
    list_select_related = ("archive", "archive__patient", "archive__doctor", "archive__doctor__user", "recorded_by")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("archive", "archive__patient", "archive__doctor", "archive__doctor__user", "recorded_by")

    @admin.display(description=_("Title"))
    def title_or_file(self, obj: ArchiveVoiceNote) -> str:
        if not obj:
            return "-"
        if getattr(obj, "title", ""):
            return obj.title
        if getattr(obj, "audio", None) and getattr(obj.audio, "name", None):
            return _safe_basename(obj.audio.name)
        return _("Voice note")

    @admin.display(description=_("Size"))
    def audio_size_display(self, obj: ArchiveVoiceNote) -> str:
        if not obj or not getattr(obj, "audio", None):
            return "-"
        try:
            return filesizeformat(obj.audio.size)
        except Exception:
            return "-"

    @admin.display(description=_("Player"))
    def player_preview(self, obj: ArchiveVoiceNote):
        return _render_voice_player(obj, width_px=260)

    def save_model(self, request, obj: ArchiveVoiceNote, form, change: bool) -> None:
        if not change and not getattr(obj, "recorded_by_id", None):
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)
