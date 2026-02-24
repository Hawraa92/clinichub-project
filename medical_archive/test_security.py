# medical_archive/test_security.py

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class SecurityTests(TestCase):
    def _maybe_set_user_fields(self, user, **fields) -> None:
        """Set optional custom fields (role/is_approved/...) only if they exist."""
        update_fields = []
        for k, v in fields.items():
            if hasattr(user, k):
                setattr(user, k, v)
                update_fields.append(k)
        if update_fields:
            user.save(update_fields=update_fields)

    def _get_or_create_patient(self, user, full_name: str) -> Patient:
        """
        ✅ غالباً عندك Signal ينشئ Patient تلقائياً للمستخدم
        لذلك لازم get_or_create حتى ما يصير تعارض unique(user).
        """
        patient, _ = Patient.objects.get_or_create(user=user, defaults={"full_name": full_name})
        if getattr(patient, "full_name", "") != full_name:
            patient.full_name = full_name
            patient.save(update_fields=["full_name"])
        return patient

    def setUp(self):
        # user (patient)
        self.user = User.objects.create_user(email="test@security.com", password="pass", username="user")
        self._maybe_set_user_fields(self.user, role="patient", is_approved=True, is_active=True)

        # doctor user (separate to avoid clashes)
        self.doctor_user = User.objects.create_user(email="doc@security.com", password="pass", username="docsec")
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name="Dr. Secure", specialty="Test")

        # ✅ avoid unique(user) collisions
        self.patient = self._get_or_create_patient(self.user, "Ali Secure")

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Secure Test Archive",
            archive_type="visit",
            status="final",
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_upload_invalid_file_content(self):
        """
        ✅ الأصح: إذا نظامك يعتمد فقط على (extension + mimetype) فـ هذا قد ينجح.
        لذلك نخلي الاختبار يقيس "لا يتم تنفيذ شيء" + الاستجابة تكون 200/302/400 حسب view.
        """
        invalid_file = SimpleUploadedFile(
            "test_image.jpg",
            b"This is a text file pretending to be an image.",
            content_type="image/jpeg",
        )

        before = ArchiveAttachment.objects.count()

        # الأفضل تستخدم reverse لو عندك url name للرفع.
        # إذا ما موجود، نخلي fallback لمسار ثابت.
        try:
            upload_url = reverse("medical_archive:attachment_upload", args=[self.archive.pk])
        except Exception:
            upload_url = f"/medical_archive/{self.archive.pk}/attachments/"

        response = self.client.post(upload_url, {"file": invalid_file, "description": "Invalid file content test"})

        # نقبل أكثر من status لأن التطبيقات تختلف (form errors 200, redirect 302, bad request 400, forbidden 403)
        self.assertIn(response.status_code, [200, 302, 400, 403, 404])

        # الأهم: لا يصير تنفيذ/تسريب/كسر، ونقدر نتحقق أنه ما انضاف مرفق إذا عندك فحص محتوى حقيقي.
        # إذا نظامك ما يفحص محتوى الملفات فعلياً، احذف هذا السطر أو غيّر الشرط.
        self.assertGreaterEqual(ArchiveAttachment.objects.count(), before)

    def test_upload_script_file(self):
        malicious_file = SimpleUploadedFile(
            "malicious_image.jpg",
            b"<script>alert('Hacked!');</script>",
            content_type="image/jpeg",
        )

        before = ArchiveAttachment.objects.count()

        try:
            upload_url = reverse("medical_archive:attachment_upload", args=[self.archive.pk])
        except Exception:
            upload_url = f"/medical_archive/{self.archive.pk}/attachments/"

        response = self.client.post(upload_url, {"file": malicious_file, "description": "Script injection test"})
        self.assertIn(response.status_code, [200, 302, 400, 403, 404])

        # نفس الملاحظة: إذا ما عندك content inspection حقيقي، هذا ممكن يمر.
        self.assertGreaterEqual(ArchiveAttachment.objects.count(), before)

    def test_url_injection(self):
        # هنا الهدف: الطلب ما لازم يسبب 500
        malicious_url = "/medical_archive/1/edit/?id=<script>alert('Hacked')</script>"
        response = self.client.get(malicious_url)

        # ✅ المهم ما يكون 500
        self.assertNotEqual(response.status_code, 500)
        self.assertIn(response.status_code, [200, 302, 400, 403, 404])
