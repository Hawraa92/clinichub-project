# File: medical_archive/pdf_utils.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string


def _load_pdf_css_text() -> str:
    """
    Try to load pdf CSS from Django staticfiles.
    Returns empty string if not found.
    """
    css_candidates = [
        "css/medical_archive/archive_export_pdf.css",
        "css/medical_archive/archive_pdf.css",
    ]
    try:
        from django.contrib.staticfiles import finders

        for rel in css_candidates:
            abs_path = finders.find(rel)
            if abs_path:
                return Path(abs_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _render_pdf_weasyprint(html: str, base_url: str) -> bytes:
    """
    Try WeasyPrint first (best rendering).
    """
    from weasyprint import HTML, CSS  # type: ignore

    stylesheets = []
    # Load CSS via filename for WeasyPrint
    try:
        from django.contrib.staticfiles import finders

        for rel in [
            "css/medical_archive/archive_export_pdf.css",
            "css/medical_archive/archive_pdf.css",
        ]:
            abs_path = finders.find(rel)
            if abs_path:
                stylesheets.append(CSS(filename=abs_path))
                break
    except Exception:
        pass

    return HTML(string=html, base_url=base_url).write_pdf(stylesheets=stylesheets)


def _render_pdf_xhtml2pdf(html: str) -> bytes:
    """
    Pure-Python fallback: xhtml2pdf (more portable).
    """
    try:
        from xhtml2pdf import pisa  # type: ignore
    except Exception as e:
        raise RuntimeError("xhtml2pdf is not installed") from e

    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result, encoding="utf-8")
    if pdf.err:
        raise RuntimeError("xhtml2pdf failed to generate PDF")
    return result.getvalue()


def build_archive_pdf_response(
    request: HttpRequest,
    *,
    archive: Any,
    attachments: Iterable[Any],
    voice_notes: Iterable[Any],
    filename: str = "medical-record.pdf",
) -> HttpResponse:
    """
    Render ONE archive PDF using an HTML template.

    Strategy:
    1) Try WeasyPrint
    2) If it fails (missing system deps, etc.), fallback to xhtml2pdf
    """
    html = render_to_string(
        "medical_archive/archive_export_pdf.html",
        {
            "archive": archive,
            "attachments": attachments,
            "voice_notes": voice_notes,
        },
        request=request,
    )

    # Base URL for resolving /static and /media when WeasyPrint is available
    base_url = request.build_absolute_uri("/")

    # For xhtml2pdf: inject CSS inline (since it doesn't use WeasyPrint stylesheets)
    css_text = _load_pdf_css_text()
    if css_text:
        if "</head>" in html:
            html = html.replace("</head>", f"<style>{css_text}</style></head>", 1)
        else:
            html = f"<style>{css_text}</style>\n{html}"

    # 1) WeasyPrint first
    pdf_bytes: bytes
    try:
        pdf_bytes = _render_pdf_weasyprint(html, base_url=base_url)
    except Exception:
        # 2) fallback
        pdf_bytes = _render_pdf_xhtml2pdf(html)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
