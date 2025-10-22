# medical_archive/test_required_fields.py

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive
from django.core.exceptions import ValidationError

User = get_user_model()

class RequiredFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@test.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Test', specialty='Neuro')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Required')

    def test_missing_title(self):
        # محاولة إنشاء أرشيف بدون عنوان
        archive = PatientArchive(
            patient=self.patient,
            doctor=self.doctor,
            title='',  # عنوان فارغ
            archive_type='visit',
            status='final'
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()

    def test_missing_doctor(self):
        # محاولة إنشاء أرشيف بدون دكتور
        archive = PatientArchive(
            patient=self.patient,
            doctor=None,
            title='Test Without Doctor',
            archive_type='visit',
            status='final'
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()

    def test_missing_patient(self):
        # محاولة إنشاء أرشيف بدون مريض
        archive = PatientArchive(
            patient=None,
            doctor=self.doctor,
            title='Test Without Patient',
            archive_type='visit',
            status='final'
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()
