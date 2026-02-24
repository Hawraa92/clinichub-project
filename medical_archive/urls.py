# File: medical_archive/urls.py
from django.urls import path

from . import views

app_name = "medical_archive"

urlpatterns = [
    # -----------------------------
    # Primary routes
    # -----------------------------
    path("", views.archive_list, name="archive_list"),
    path("create/", views.create_archive, name="create_archive"),

    path("archive/<int:archive_id>/", views.archive_detail, name="archive_detail"),
    path("archive/<int:archive_id>/edit/", views.edit_archive, name="edit_archive"),
    path("archive/<int:archive_id>/delete/", views.delete_archive, name="delete_archive"),

    # Exports
    path("archive/<int:archive_id>/export/pdf/", views.export_archive_pdf, name="export_archive_pdf"),

    # Downloads
    path("attachments/<int:attachment_id>/download/", views.download_attachment, name="download_attachment"),
    path("voice-notes/<int:voice_id>/download/", views.download_voice_note, name="download_voice_note"),

    # -----------------------------
    # Optional aliases (keep if your templates use them)
    # -----------------------------
    path("archives/", views.archive_list, name="archives_list_alias"),
    path("archives/new/", views.create_archive, name="archives_create_alias"),
    path("archives/<int:archive_id>/", views.archive_detail, name="archives_detail_alias"),
    path("archives/<int:archive_id>/update/", views.edit_archive, name="archives_edit_alias"),
    path("archives/<int:archive_id>/remove/", views.delete_archive, name="archives_delete_alias"),

    # ✅ Alias for export to avoid breaking older templates/links
    path("archives/<int:archive_id>/export/pdf/", views.export_archive_pdf, name="archives_export_pdf_alias"),
]
