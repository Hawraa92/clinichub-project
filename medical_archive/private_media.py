from __future__ import annotations

import mimetypes
import os
import re

from django.contrib.auth.decorators import (
    login_required,
    permission_required,
)
from django.http import (
    FileResponse,
    Http404,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header

from .access import is_authorized_for_archive
from .models import (
    ArchiveAttachment,
    ArchiveVoiceNote,
)


PERM_VIEW_ARCHIVE = (
    "medical_archive.view_patientarchive"
)
PERM_VIEW_ATTACHMENT = (
    "medical_archive.view_archiveattachment"
)
PERM_VIEW_VOICE_NOTE = (
    "medical_archive.view_archivevoicenote"
)

RANGE_PATTERN = re.compile(
    r"bytes=(\d*)-(\d*)$"
)


def _secure_headers(response):
    response["Cache-Control"] = (
        "private, no-store, max-age=0"
    )
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "style-src 'unsafe-inline'"
    )
    return response


def _open_field_file(field_file):
    if (
        not field_file
        or not getattr(field_file, "name", None)
    ):
        raise Http404("File not found.")

    try:
        return field_file.open("rb")
    except Exception as exc:
        raise Http404(
            "File not available."
        ) from exc


def _content_type(filename, default):
    guessed, _encoding = mimetypes.guess_type(
        filename
    )
    return guessed or default


@login_required
@permission_required(
    (
        PERM_VIEW_ARCHIVE,
        PERM_VIEW_ATTACHMENT,
    ),
    raise_exception=True,
)
def preview_attachment(
    request,
    attachment_id,
):
    attachment = get_object_or_404(
        ArchiveAttachment.objects.select_related(
            "archive",
            "archive__patient",
            "archive__patient__user",
            "archive__doctor",
            "archive__doctor__user",
            "archive__appointment",
        ),
        pk=attachment_id,
    )

    if not is_authorized_for_archive(
        request.user,
        attachment.archive,
    ):
        raise Http404("Not found.")

    filename = os.path.basename(
        attachment.file.name
    )
    file_handle = _open_field_file(
        attachment.file
    )

    response = FileResponse(
        file_handle,
        as_attachment=False,
        filename=filename,
        content_type=_content_type(
            filename,
            "application/octet-stream",
        ),
    )

    return _secure_headers(response)


def _partial_file_iterator(
    file_handle,
    length,
    chunk_size=64 * 1024,
):
    remaining = length

    try:
        while remaining > 0:
            data = file_handle.read(
                min(chunk_size, remaining)
            )

            if not data:
                break

            remaining -= len(data)
            yield data
    finally:
        file_handle.close()


@login_required
@permission_required(
    (
        PERM_VIEW_ARCHIVE,
        PERM_VIEW_VOICE_NOTE,
    ),
    raise_exception=True,
)
def stream_voice_note(
    request,
    voice_id,
):
    voice = get_object_or_404(
        ArchiveVoiceNote.objects.select_related(
            "archive",
            "archive__patient",
            "archive__patient__user",
            "archive__doctor",
            "archive__doctor__user",
            "archive__appointment",
        ),
        pk=voice_id,
    )

    if not is_authorized_for_archive(
        request.user,
        voice.archive,
    ):
        raise Http404("Not found.")

    if (
        not voice.audio
        or not getattr(voice.audio, "name", None)
    ):
        raise Http404("Audio not found.")

    filename = os.path.basename(
        voice.audio.name
    )
    content_type = _content_type(
        filename,
        "application/octet-stream",
    )

    try:
        size = voice.audio.size
    except Exception as exc:
        raise Http404(
            "Audio not available."
        ) from exc

    range_header = (
        request.headers.get("Range") or ""
    ).strip()

    match = RANGE_PATTERN.match(
        range_header
    )

    if not match:
        file_handle = _open_field_file(
            voice.audio
        )

        response = FileResponse(
            file_handle,
            as_attachment=False,
            filename=filename,
            content_type=content_type,
        )
        response["Accept-Ranges"] = "bytes"

        return _secure_headers(response)

    start_text, end_text = match.groups()

    if not start_text and not end_text:
        raise Http404("Invalid range.")

    if start_text:
        start = int(start_text)
        end = (
            int(end_text)
            if end_text
            else size - 1
        )
    else:
        suffix_length = int(end_text)

        if suffix_length <= 0:
            raise Http404("Invalid range.")

        start = max(0, size - suffix_length)
        end = size - 1

    if (
        start < 0
        or end < start
        or start >= size
    ):
        raise Http404("Invalid range.")

    end = min(end, size - 1)
    length = end - start + 1

    file_handle = _open_field_file(
        voice.audio
    )
    file_handle.seek(start)

    response = StreamingHttpResponse(
        _partial_file_iterator(
            file_handle,
            length,
        ),
        status=206,
        content_type=content_type,
    )

    response["Content-Length"] = str(length)
    response["Content-Range"] = (
        f"bytes {start}-{end}/{size}"
    )
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = (
        content_disposition_header(
            False,
            filename,
        )
    )

    return _secure_headers(response)
