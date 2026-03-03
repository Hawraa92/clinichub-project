# doctor/tests/test_forms.py
from __future__ import annotations

from io import BytesIO

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from doctor.forms import DoctorProfileForm
from doctor.models import Doctor

User = get_user_model()


def make_real_jpeg_bytes() -> bytes:
    """
    Generate a REAL JPEG in memory so Doctor image validation passes.
    """
    from PIL import Image  # pillow موجود عندك
    buf = BytesIO()
    Image.new("RGB", (20, 20)).save(buf, format="JPEG")
    return buf.getvalue()


class DoctorProfileFormTests(TestCase):
    def setUp(self):
        # Create a doctor user and profile
        self.user = User.objects.create_user(
            username="doc1",
            email="doc1@example.com",
            password="testpass",
            role="doctor",
        )

        # خلي الاسم مو فاضي حتى full_name يكون مضبوط
        self.user.first_name = "Test"
        self.user.last_name = "Doctor"
        self.user.save(update_fields=["first_name", "last_name"])

        self.doctor = Doctor.objects.create(
            user=self.user,
            specialty="Cardiology",
        )

        # Default form data (strings to simulate POST)
        # ✅ رقم صالح بصيغة دولية
        self.valid_data = {
            "full_name": getattr(self.doctor, "full_name", self.user.get_full_name()),
            "specialty": self.doctor.specialty,
            "gender": "male",
            "phone": "+9647701234567",  # ✅ valid
            "clinic_address": "123 Main St",
            "short_bio": "Experienced cardiologist",
            "available": "on",  # checkbox
            "consultation_fee": "100",
            "delete_photo": False,
        }

    def test_form_valid(self):
        """Form is valid with correct data."""
        form = DoctorProfileForm(data=self.valid_data, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()
        self.assertEqual(int(doc.consultation_fee), 100)

    def test_readonly_fields_unchanged(self):
        """Full name and specialty remain unchanged even if passed differently."""
        data = self.valid_data.copy()
        data["full_name"] = "Hacker"
        data["specialty"] = "Dermatology"

        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()

        # Read-only should not change
        self.assertNotEqual(getattr(doc, "full_name", ""), "Hacker")
        self.assertEqual(getattr(doc, "full_name", self.user.get_full_name()), getattr(self.doctor, "full_name", self.user.get_full_name()))
        self.assertNotEqual(doc.specialty, "Dermatology")
        self.assertEqual(doc.specialty, self.doctor.specialty)

    def test_phone_invalid(self):
        """Invalid phone should raise ValidationError."""
        data = self.valid_data.copy()
        data["phone"] = "abc123"
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_consultation_fee_negative(self):
        """Negative consultation_fee should be invalid."""
        data = self.valid_data.copy()
        data["consultation_fee"] = "-50"
        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertFalse(form.is_valid())
        self.assertIn("consultation_fee", form.errors)

    def test_delete_photo_removes_file(self):
        """Toggling delete_photo removes existing photo."""
        # ✅ Attach REAL photo bytes so model validation passes
        self.doctor.photo.save("photo.jpg", ContentFile(make_real_jpeg_bytes()), save=False)
        self.doctor.save()

        data = self.valid_data.copy()
        data["delete_photo"] = True

        form = DoctorProfileForm(data=data, files={}, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save()
        self.assertFalse(bool(doc.photo))

    def test_disable_fields_flag(self):
        """Disabled fields are set to unchanged values on clean."""
        data = self.valid_data.copy()
        # even if someone tries to change read-only fields in POST
        data["full_name"] = "Malicious"
        data["specialty"] = "Hacking"

        form = DoctorProfileForm(data=data, instance=self.doctor)
        self.assertTrue(form.is_valid(), form.errors)

        cleaned = form.clean()
        self.assertEqual(cleaned["full_name"], self.valid_data["full_name"])
        self.assertEqual(cleaned["specialty"], self.valid_data["specialty"])