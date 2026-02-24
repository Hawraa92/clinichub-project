# medical_archive/test_multi_attachment.py

from __future__ import annotations

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class MultiAttachmentTests(TestCase):
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
        # ✅ Users منفصلين حتى ما يصير تعارض Patient.user (لازم يكون فريد)
        self.doctor_user = User.objects.create_user(
            email="multi_doctor@test.com",
            password="pass",
            username="multi_doctor_user",
        )
        self.patient_user = User.objects.create_user(
            email="multi_patient@test.com",
            password="pass",
            username="multi_patient_user",
        )

        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Omar",
            specialty="Eye",
        )

        self.patient, _created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={"full_name": "Ali Attach"},
        )

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attach Record",
            archive_type="visit",
            status="final",
        )

    def test_add_and_remove_attachments(self):
        # رفع ملفين للأرشيف نفسه
        file1 = SimpleUploadedFile("lab1.pdf", b"file_content_1", content_type="application/pdf")
        file2 = SimpleUploadedFile("scan1.jpg", b"file_content_2", content_type="image/jpeg")

        att1 = ArchiveAttachment.objects.create(
            archive=self.archive, file=file1, description="Lab Result"
        )
        att2 = ArchiveAttachment.objects.create(
            archive=self.archive, file=file2, description="Scan Result"
        )

        # تحقق أن المرفقين انحفظوا
        self.assertEqual(self.archive.attachments.count(), 2)
        self.assertTrue(ArchiveAttachment.objects.filter(pk=att1.pk).exists())
        self.assertTrue(ArchiveAttachment.objects.filter(pk=att2.pk).exists())

        # حذف أحد المرفقات
        att1.delete()

        # تحقق أن الثاني باقٍ فقط
        attachments = self.archive.attachments.all()
        self.assertEqual(attachments.count(), 1)
        self.assertFalse(ArchiveAttachment.objects.filter(pk=att1.pk).exists())
        self.assertTrue(ArchiveAttachment.objects.filter(pk=att2.pk).exists())
        self.assertEqual(attachments.first().description, "Scan Result")
