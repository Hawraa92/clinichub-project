# File: medical_archive/pdf_utils.py
from __future__ import annotations

from typing import Any, Iterable, Optional

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string


def build_archive_pdf_response(
    request: HttpRequest,
    *,
    archive: Any,
    attachments: Iterable[Any],
    voice_notes: Iterable[Any],
    filename: str = "medical-record.pdf",
) -> HttpResponse:
    """
    Render ONE archive PDF using an HTML template (WeasyPrint).

    ✅ Works well on Windows/dev:
    - Uses absolute base_url so static/media URLs resolve
    - Loads CSS via Django staticfiles finders (instead of relying on <link> tags)
    - Falls back gracefully if CSS file is not found

    Requirements:
      pip install weasyprint
    """
    try:
        from weasyprint import HTML, CSS  # type: ignore
    except Exception as e:
        raise RuntimeError("WeasyPrint is not installed. Run: pip install weasyprint") from e

    # 1) Render HTML
    html = render_to_string(
        "medical_archive/archive_export_pdf.html",
        {
            "archive": archive,
            "attachments": attachments,
            "voice_notes": voice_notes,
        },
        request=request,
    )

    # 2) base_url is critical for resolving:
    #    - /static/...
    #    - /media/...
    #    - any relative links
    base_url = request.build_absolute_uri("/")

    # 3) Load CSS reliably from Django staticfiles
    stylesheets = []

    # primary: pdf-specific css (recommended)
    _try_css_paths = [
        "css/medical_archive/archive_export_pdf.css",
        # fallback names if you ever change naming:
        "css/medical_archive/archive_pdf.css",
    ]

    try:
        from django.contrib.staticfiles import finders

        for rel_path in _try_css_paths:
            abs_path = finders.find(rel_path)
            if abs_path:
                stylesheets.append(CSS(filename=abs_path))
                break
    except Exception:
        # If staticfiles isn't configured, just continue without CSS
        pass

    # 4) Build PDF
    pdf_bytes = HTML(string=html, base_url=base_url).write_pdf(stylesheets=stylesheets)

    # 5) Response
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
