# medical_archive/test_multi_attachment.py

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class MultiAttachmentTests(TestCase):
    def setUp(self):
        # إنشاء مستخدم وطبيب ومريض
        self.user = User.objects.create_user(email='test@test.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Omar', specialty='Eye')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Attach')
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attach Record",
            archive_type='visit',
            status='final'
        )

    def test_add_and_remove_attachments(self):
        # رفع ملفين للأرشيف نفسه
        file1 = SimpleUploadedFile("lab1.pdf", b"file_content_1", content_type="application/pdf")
        file2 = SimpleUploadedFile("scan1.jpg", b"file_content_2", content_type="image/jpeg")
        att1 = ArchiveAttachment.objects.create(archive=self.archive, file=file1, description='Lab Result')
        att2 = ArchiveAttachment.objects.create(archive=self.archive, file=file2, description='Scan Result')

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
        self.assertEqual(attachments.first().description, 'Scan Result')
