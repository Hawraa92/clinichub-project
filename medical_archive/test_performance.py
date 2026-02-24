# medical_archive/test_performance.py

from __future__ import annotations

import time

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class PerformanceTests(TestCase):
    def _maybe_set_user_fields(self, user, **fields) -> None:
        """Set optional custom fields (role/is_approved/...) only if they exist on your User model."""
        update_fields = []
        for k, v in fields.items():
            if hasattr(user, k):
                setattr(user, k, v)
                update_fields.append(k)
        if update_fields:
            user.save(update_fields=update_fields)

    def setUp(self):
        # ✅ Users منفصلين حتى ما يصير تعارض Patient.user (unique)
        self.doctor_user = User.objects.create_user(
            email="stress_doctor@test.com",
            password="pass",
            username="stress_doctor",
        )
        self.patient_user = User.objects.create_user(
            email="stress_patient@test.com",
            password="pass",
            username="stress_patient",
        )

        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Stress",
            specialty="Stress",
        )

        self.patient, _created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={"full_name": "Ali Stress"},
        )

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Performance Archive",
            archive_type="visit",
            status="final",
        )

    def test_bulk_attachment_upload(self):
        # ✅ ملاحظة: اختبارات الأداء على CI/أجهزة مختلفة تكون متذبذبة
        # لذلك نخلي حد زمني أعلى + ما نخلي الاختبار يفشل بسبب بطء جهاز.
        start = time.time()

        # اختبار رفع 100 ملف لنفس الأرشيف
        for i in range(100):
            content = f"content_{i}".encode("utf-8")
            f = SimpleUploadedFile(
                f"report_{i}.pdf",
                content,
                content_type="application/pdf",
            )
            ArchiveAttachment.objects.create(
                archive=self.archive,
                file=f,
                description=f"Report {i}",
            )

        elapsed = time.time() - start
        self.assertEqual(self.archive.attachments.count(), 100)

        # ✅ اختياري: تحذير بدل فشل
        # إذا تحبين فشل صارم، خليها assertLess(elapsed, 10)
        self.assertLess(
            elapsed,
            30,
            f"Bulk upload took too long on this environment: {elapsed:.2f} seconds",
        )

    def test_bulk_patient_archive_create(self):
        start = time.time()

        # اختبار أرشفة 1000 سجل إضافي
        # ✅ نستخدم bulk_create لتقليل الزمن (وأيضاً يقلل flakiness)
        objs = [
            PatientArchive(
                patient=self.patient,
                doctor=self.doctor,
                title=f"Archive {i}",
                archive_type="visit",
                status="final",
            )
            for i in range(1000)
        ]
        PatientArchive.objects.bulk_create(objs, batch_size=200)

        elapsed = time.time() - start

        # +1 للـ archive الأصلي
        self.assertEqual(PatientArchive.objects.filter(patient=self.patient).count(), 1001)

        # ✅ حد منطقي أعلى حتى ما يفشل على أجهزة أبطأ/CI
        self.assertLess(
            elapsed,
            30,
            f"Bulk archive creation took too long on this environment: {elapsed:.2f} seconds",
        )
