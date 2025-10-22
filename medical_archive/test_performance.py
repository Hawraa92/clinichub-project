# medical_archive/test_performance.py

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment
import time

User = get_user_model()

class PerformanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='stress@test.com', password='pass', username='stress')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Stress', specialty='Stress')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Stress')
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Performance Archive",
            archive_type='visit',
            status='final'
        )

    def test_bulk_attachment_upload(self):
        # اختبار رفع 100 ملف لنفس الأرشيف
        start = time.time()
        for i in range(100):
            file = SimpleUploadedFile(f"report_{i}.pdf", b"content_%d" % i, content_type="application/pdf")
            ArchiveAttachment.objects.create(archive=self.archive, file=file, description=f"Report {i}")
        elapsed = time.time() - start

        self.assertEqual(self.archive.attachments.count(), 100)
        # اختبار سرعة: أقل من 10 ثواني (اختياري حسب جهازك)
        self.assertLess(elapsed, 10, f"Bulk upload took too long: {elapsed:.2f} seconds")

    def test_bulk_patient_archive_create(self):
        # اختبار أرشفة 1000 سجل
        start = time.time()
        for i in range(1000):
            PatientArchive.objects.create(
                patient=self.patient,
                doctor=self.doctor,
                title=f"Archive {i}",
                archive_type='visit',
                status='final'
            )
        elapsed = time.time() - start

        self.assertEqual(PatientArchive.objects.filter(patient=self.patient).count(), 1001)  # +1 للـ archive الأصلي
        # اختبار سرعة: أقل من 15 ثانية (اختياري حسب الجهاز)
        self.assertLess(elapsed, 15, f"Bulk archive creation took too long: {elapsed:.2f} seconds")
