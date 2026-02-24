# medical_archive/test_pdf_utils.py
from __future__ import annotations

from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from medical_archive import pdf_utils


class PDFUtilsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @mock.patch(
        "medical_archive.pdf_utils.render_to_string",
        return_value="<html><body><h1>OK</h1></body></html>",
    )
    @mock.patch(
        "medical_archive.pdf_utils._render_pdf_weasyprint",
        return_value=b"%PDF-FAKE\n%EOF\n",
    )
    def test_pdf_weasyprint_success(self, _weasy, _rts):
        request = self.factory.get("/")
        resp = pdf_utils.build_archive_pdf_response(
            request,
            archive=object(),
            attachments=[],
            voice_notes=[],
            filename="t.pdf",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="t.pdf"', resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"%PDF"))

    @mock.patch(
        "medical_archive.pdf_utils.render_to_string",
        return_value="<html><body><h1>OK</h1></body></html>",
    )
    @mock.patch(
        "medical_archive.pdf_utils._render_pdf_weasyprint",
        side_effect=RuntimeError("weasyprint unavailable"),
    )
    @mock.patch(
        "medical_archive.pdf_utils._render_pdf_xhtml2pdf",
        return_value=b"%PDF-FAKE\n%EOF\n",
    )
    def test_pdf_fallback_to_xhtml2pdf(self, _xh, _weasy, _rts):
        request = self.factory.get("/")
        resp = pdf_utils.build_archive_pdf_response(
            request,
            archive=object(),
            attachments=[],
            voice_notes=[],
            filename="t.pdf",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"%PDF"))

    @mock.patch(
        "medical_archive.pdf_utils.render_to_string",
        return_value="<html><body><h1>OK</h1></body></html>",
    )
    @mock.patch(
        "medical_archive.pdf_utils._render_pdf_weasyprint",
        side_effect=RuntimeError("weasyprint failed"),
    )
    @mock.patch(
        "medical_archive.pdf_utils._render_pdf_xhtml2pdf",
        side_effect=RuntimeError("xhtml2pdf failed"),
    )
    def test_pdf_raises_when_both_renderers_fail(self, _xh, _weasy, _rts):
        request = self.factory.get("/")
        with self.assertRaises(RuntimeError):
            pdf_utils.build_archive_pdf_response(
                request,
                archive=object(),
                attachments=[],
                voice_notes=[],
                filename="t.pdf",
            )
