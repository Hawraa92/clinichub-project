# medical_archive/test_download_preview.py

from __future__ import annotations

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class DownloadPreviewTests(TestCase):
    def _maybe_set_user_fields(self, user, **fields) -> None:
        """Set optional custom fields (role/is_approved/...) only if they exist on your User model."""
        update_fields = []
        for k, v in fields.items():
            if hasattr(user, k):
                setattr(user, k, v)
                update_fields.append(k)
        if update_fields:
            user.save(update_fields=update_fields)

    def _resp_bytes(self, response) -> bytes:
        """Support both StreamingHttpResponse and normal HttpResponse."""
        if getattr(response, "streaming", False):
            return b"".join(response.streaming_content)
        return response.content

    def setUp(self):
        # ✅ استخدم Users منفصلين حتى ما يصير تعارض (Patient user لازم يكون فريد)
        self.doctor_user = User.objects.create_user(
            email="doctor@download.com",
            password="pass",
            username="doctor_user",
        )
        self.patient_user = User.objects.create_user(
            email="patient@download.com",
            password="pass",
            username="patient_user",
        )

        # (اختياري) إذا عندك حقول role/is_approved بالموديل
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Preview",
            specialty="Lab",
        )

        # ✅ لا تستخدم نفس user مال الدكتور للمريض
        self.patient, _created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={"full_name": "Ali Preview"},
        )

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Preview Record",
            archive_type="lab",
            status="final",
        )

        # رفع صورة و PDF
        self.img_bytes = b"\x89PNG\r\n\x1a\nimgcontent"
        self.pdf_bytes = b"%PDF-1.4 pdfcontent"

        self.img_attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("xray.png", self.img_bytes, content_type="image/png"),
            description="X-ray",
        )
        self.pdf_attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("report.pdf", self.pdf_bytes, content_type="application/pdf"),
            description="Lab Report",
        )

        self.client = Client()
        # ✅ نسجل دخول كـ doctor user (الأغلب view التحميل محمي)
        self.client.login(email="doctor@download.com", password="pass")

    def test_download_attachment_and_compare_bytes(self):
        # تحميل ملف الصورة عبر view التحميل المحمي وتطابق البايتات
        file_url = reverse("medical_archive:download_attachment", args=[self.img_attachment.pk])
        response = self.client.get(file_url)
        self.assertEqual(response.status_code, 200)
        actual_img_bytes = self._resp_bytes(response)
        self.assertEqual(actual_img_bytes, self.img_bytes)

        # تحميل ملف PDF عبر view التحميل المحمي وتطابق البايتات
        pdf_url = reverse("medical_archive:download_attachment", args=[self.pdf_attachment.pk])
        response2 = self.client.get(pdf_url)
        self.assertEqual(response2.status_code, 200)
        actual_pdf_bytes = self._resp_bytes(response2)
        self.assertEqual(actual_pdf_bytes, self.pdf_bytes)

    def test_image_and_pdf_preview(self):
        # تأكدي أن image_tag تعرض img
        self.assertTrue(self.img_attachment.is_image())
        self.assertIn("<img", str(self.img_attachment.image_tag()))

        # تأكدي أن PDF لا يعرض img (يعرض "-")
        self.assertTrue(self.pdf_attachment.is_pdf())
        self.assertFalse(self.pdf_attachment.is_image())
        self.assertEqual(str(self.pdf_attachment.image_tag()), "-")
