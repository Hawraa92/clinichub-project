# doctor/tests/test_forms.py

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from doctor.forms import DoctorProfileForm
from doctor.models import Doctor

User = get_user_model()

class DoctorProfileFormTests(TestCase):
    def setUp(self):
        # Create a doctor user and profile
        self.user = User.objects.create_user(
            username='doc1',
            email='doc1@example.com',
            password='testpass',
            role='doctor'
        )
        self.doctor = Doctor.objects.create(
            user=self.user,
            specialty='Cardiology'
        )
        # Default form data (strings to simulate POST)
        self.valid_data = {
            'full_name': self.doctor.full_name,
            'specialty': self.doctor.specialty,
            'gender': 'male',
            'phone': '+1234567890',
            'clinic_address': '123 Main St',
            'short_bio': 'Experienced cardiologist',
            'available': 'on',  # checkbox
            'consultation_fee': '100',
            'delete_photo': False,
        }

    def test_form_valid(self):
        """Form is valid with correct data."""
        form = DoctorProfileForm(data=self.valid_data, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()
        self.assertEqual(doc.consultation_fee, 100)

    def test_readonly_fields_unchanged(self):
        """Full name and specialty remain unchanged even if passed differently."""
        data = self.valid_data.copy()
        data['full_name'] = 'Hacker'
        data['specialty'] = 'Dermatology'
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()
        # Read-only should not change
        self.assertNotEqual(doc.full_name, 'Hacker')
        self.assertEqual(doc.full_name, self.doctor.full_name)
        self.assertNotEqual(doc.specialty, 'Dermatology')

    def test_phone_invalid(self):
        """Invalid phone should raise ValidationError."""
        data = self.valid_data.copy()
        data['phone'] = 'abc123'
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_consultation_fee_negative(self):
        """Negative consultation_fee should be invalid."""
        data = self.valid_data.copy()
        data['consultation_fee'] = '-50'
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertFalse(form.is_valid())
        self.assertIn('consultation_fee', form.errors)

    def test_delete_photo_removes_file(self):
        """Toggling delete_photo removes existing photo."""
        # Attach dummy photo
        img = SimpleUploadedFile('photo.jpg', b'1234', content_type='image/jpeg')
        self.doctor.photo = img
        self.doctor.save()

        data = self.valid_data.copy()
        data['delete_photo'] = True
        form = DoctorProfileForm(data=data, files={}, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()
        self.assertFalse(doc.photo)

    def test_disable_fields_flag(self):
        """Disabled fields are set to unchanged values on clean."""
        data = self.valid_data.copy()
        # even if someone tries to change read-only fields in POST
        data['full_name'] = 'Malicious'
        data['specialty'] = 'Hacking'
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertTrue(form.is_valid())
        cleaned = form.clean()
        self.assertEqual(cleaned['full_name'], self.doctor.full_name)
        self.assertEqual(cleaned['specialty'], self.doctor.specialty)
