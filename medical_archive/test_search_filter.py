# medical_archive/test_search_filter.py

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive

User = get_user_model()


class ArchiveSearchAndFilterTests(TestCase):
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
        # مستخدم (المريض)
        self.user = User.objects.create_user(email="test@test.com", password="pass", username="pat")
        self._maybe_set_user_fields(self.user, role="patient", is_approved=True, is_active=True)

        # مستخدم (الطبيب)
        self.doctor_user = User.objects.create_user(email="doc@test.com", password="pass", username="doc")
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)

        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name="Dr. Omar", specialty="Heart")

        # ✅ بدل Patient.objects.create(...) حتى ما يضرب unique(user)
        self.patient = self._get_or_create_patient(self.user, "Ali Search")

        self.client = Client()
        # ✅ أوثق من client.login إذا عندك Backend خاص
        self.client.force_login(self.user)

        # أرشيفات متنوعة (created_at لازم يكون datetime مو date)
        now = timezone.now()
        self.archive1 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Diabetes Lab",
            archive_type="lab",
            status="final",
            created_at=now - timedelta(days=10),
        )
        self.archive2 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Chest Scan Result",
            archive_type="scan",
            status="final",
            created_at=now - timedelta(days=5),
        )
        self.archive3 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit for Fever",
            archive_type="visit",
            status="final",
            created_at=now,
        )

    def test_search_by_title(self):
        url = reverse("medical_archive:archive_list")
        response = self.client.get(url, {"search": "Diabetes"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diabetes Lab")
        self.assertNotContains(response, "Chest Scan Result")
        self.assertNotContains(response, "Visit for Fever")

    def test_filter_by_type(self):
        url = reverse("medical_archive:archive_list")
        response = self.client.get(url, {"type": "scan"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chest Scan Result")
        self.assertNotContains(response, "Diabetes Lab")
        self.assertNotContains(response, "Visit for Fever")

    def test_filter_by_date_range(self):
        url = reverse("medical_archive:archive_list")

        # يفترض فقط تظهر أرشيفات من 6 أيام إلى اليوم
        start = (timezone.localdate() - timedelta(days=6)).isoformat()
        response = self.client.get(url, {"start_date": start})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chest Scan Result")
        self.assertContains(response, "Visit for Fever")
        self.assertNotContains(response, "Diabetes Lab")

        # فلترة فقط اليوم الحالي
        today = timezone.localdate().isoformat()
        response2 = self.client.get(url, {"start_date": today, "end_date": today})
        self.assertEqual(response2.status_code, 200)
        self.assertContains(response2, "Visit for Fever")
        self.assertNotContains(response2, "Diabetes Lab")
        self.assertNotContains(response2, "Chest Scan Result")
