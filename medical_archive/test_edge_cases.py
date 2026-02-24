# medical_archive/test_edge_cases.py

from __future__ import annotations

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class EdgeCasesTests(TestCase):
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
        # ✅ Users منفصلين حتى ما يصير تعارض (Patient user لازم يكون فريد)
        self.doctor_user = User.objects.create_user(
            email="edge_doctor@test.com",
            password="pass",
            username="edge_doctor_user",
        )
        self.patient_user = User.objects.create_user(
            email="edge_patient@test.com",
            password="pass",
            username="edge_patient_user",
        )

        # (اختياري) إذا عندك حقول role/is_approved بالموديل
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="د. استثناء",
            specialty="اختبار",
        )

        self.patient, _created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={"full_name": "محمد حروف خاصة"},
        )

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="سجل تجريبي 🎉 اختبار ملفات",
            archive_type="lab",
            status="final",
        )

        self.client = Client()
        # ✅ نسجل دخول كـ doctor user (الأغلب عندك صلاحيات التحميل للطاقم)
        self.client.login(email="edge_doctor@test.com", password="pass")

    def test_upload_unicode_filename_attachment(self):
        # رفع ملف اسمه بالعربي أو فيه Unicode
        arabic_filename = "تقرير_نهائي_عربي😊.pdf"
        file_bytes = b"EDGE_TEST"

        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile(arabic_filename, file_bytes, content_type="application/pdf"),
            description="ملف عربي",
        )

        # ✔️ جربي التحميل وتحققي من محتوى الملف (المسار غالباً UUID)
        download_url = reverse("medical_archive:download_attachment", args=[attachment.pk])
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, 200)

        actual_bytes = self._resp_bytes(response)
        self.assertEqual(actual_bytes, file_bytes)

    def test_delete_archive_deletes_attachments(self):
        # أضف مرفقات
        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("test1.pdf", b"1", content_type="application/pdf"),
        )
        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("test2.png", b"2", content_type="image/png"),
        )

        # تأكد أن الاثنين موجودين
        self.assertEqual(ArchiveAttachment.objects.filter(archive=self.archive).count(), 2)

        # احذف الأرشيف (cascade)
        archive_pk = self.archive.pk
        self.archive.delete()

        # تأكد أن جميع المرفقات انحذفت معه
        self.assertEqual(ArchiveAttachment.objects.filter(archive_id=archive_pk).count(), 0)
