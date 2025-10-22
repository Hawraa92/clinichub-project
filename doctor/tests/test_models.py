# doctor/tests/test_models.py

import re
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from doctor.models import Doctor, phone_validator

User = get_user_model()

class DoctorModelTests(TestCase):
    def setUp(self):
        # Create a user with doctor role
        self.user = User.objects.create_user(
            username='testdoc',
            email='testdoc@example.com',
            password='pwd',
            role='doctor'
        )

    def test_str_returns_full_name(self):
        doc = Doctor.objects.create(
            user=self.user,
            specialty='Cardiology',
            full_name='Dr. Test'
        )
        self.assertEqual(str(doc), 'Dr. Test')

    def test_str_fallback_to_username(self):
        doc = Doctor.objects.create(
            user=self.user,
            specialty='Cardiology'
        )
        # full_name auto-filled to username
        self.assertEqual(str(doc), self.user.username)

    def test_auto_fill_full_name(self):
        doc = Doctor.objects.create(
            user=self.user,
            specialty='Dermatology'
        )
        self.assertEqual(doc.full_name, self.user.username)

    def test_get_absolute_url(self):
        doc = Doctor.objects.create(
            user=self.user,
            specialty='Neurology'
        )
        expected = reverse('doctor:detail', args=[doc.pk])
        self.assertEqual(doc.get_absolute_url(), expected)

    def test_phone_validator_accepts_valid_and_rejects_invalid(self):
        # Valid cases
        valid_numbers = ['+1234567', '123456789012345']  # 7 digits and 15 digits
        for num in valid_numbers:
            phone_validator(num)
        # Invalid: non-digits
        with self.assertRaises(ValidationError):
            phone_validator('abc123')
        # Invalid: too long (16 digits)
        with self.assertRaises(ValidationError):
            phone_validator('+1234567890123456')

    def test_clean_strips_spaces(self):
        doc = Doctor(
            user=self.user,
            specialty='Pediatrics',
            phone='+123 456 789'
        )
        doc.clean()
        self.assertEqual(doc.phone, '+123456789')

    def test_clean_rejects_blank_full_name(self):
        doc = Doctor(
            user=self.user,
            specialty='Pediatrics',
            full_name='   '
        )
        with self.assertRaises(ValidationError):
            doc.full_clean()

    def test_rating_constraints(self):
        # Within range
        doc = Doctor(
            user=self.user,
            specialty='General',
            rating=0
        )
        doc.full_clean()
        doc.rating = 5
        doc.full_clean()
        doc.rating = 4.5
        doc.full_clean()
        # Out of range
        for bad in [-1, 5.1]:
            doc.rating = bad
            with self.assertRaises(ValidationError):
                doc.full_clean()

    def test_consultation_fee_non_negative(self):
        doc = Doctor(
            user=self.user,
            specialty='Test',
            consultation_fee=-10
        )
        with self.assertRaises(ValidationError):
            doc.full_clean()
        # Zero is allowed
        doc.consultation_fee = 0
        doc.full_clean()

    def test_experience_years_non_negative(self):
        doc = Doctor(
            user=self.user,
            specialty='Test',
            experience_years=-1
        )
        with self.assertRaises(ValidationError):
            doc.full_clean()
        doc.experience_years = 5
        doc.full_clean()

    def test_default_available_true(self):
        doc = Doctor.objects.create(
            user=self.user,
            specialty='Test'
        )
        self.assertTrue(doc.available)

    def test_photo_extension_invalid(self):
        doc = Doctor(
            user=self.user,
            specialty='Test'
        )
        # Attach a .txt file to photo
        doc.photo = SimpleUploadedFile('test.txt', b'data')
        with self.assertRaises(ValidationError):
            doc.full_clean()

    def test_ordering(self):
        # Create multiple doctors, ensure ordering by full_name
        u2 = User.objects.create_user(
            username='aaa',
            email='aaa@example.com',
            password='pwd',
            role='doctor'
        )
        d1 = Doctor.objects.create(user=self.user, specialty='X')
        d2 = Doctor.objects.create(user=u2, specialty='Y')
        names = [d.full_name for d in Doctor.objects.all()]
        self.assertEqual(names, sorted(names))
