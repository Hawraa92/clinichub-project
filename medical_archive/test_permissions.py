# medical_archive/test_permissions.py

from __future__ import annotations

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive

User = get_user_model()


class ArchiveAccessPermissionTests(TestCase):
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
        ✅ مهم: عندك غالباً Signal يسوي Patient تلقائياً للمستخدم
        لذلك نستخدم get_or_create حتى ما يصير تعارض unique(user).
        """
        patient, _ = Patient.objects.get_or_create(user=user, defaults={"full_name": full_name})
        # لو موجود مسبقاً وتريدين تضمنين الاسم
        if getattr(patient, "full_name", "") != full_name:
            patient.full_name = full_name
            patient.save(update_fields=["full_name"])
        return patient

    def setUp(self):
        # ===== Patient 1 (owner) =====
        self.user1 = User.objects.create_user(email="patient1@test.com", password="pass", username="pat1")
        self._maybe_set_user_fields(self.user1, role="patient", is_approved=True, is_active=True)
        self.patient1 = self._get_or_create_patient(self.user1, "Ali Ahmed")

        # ===== Doctor =====
        self.doctor_user = User.objects.create_user(email="doc@test.com", password="pass", username="doc")
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name="Dr. Test", specialty="Cardiology")

        # ===== Patient 2 (not allowed) =====
        self.user2 = User.objects.create_user(email="patient2@test.com", password="pass", username="pat2")
        self._maybe_set_user_fields(self.user2, role="patient", is_approved=True, is_active=True)
        self.patient2 = self._get_or_create_patient(self.user2, "Zainab Other")

        # ===== Archive for patient 1 =====
        self.archive = PatientArchive.objects.create(
            patient=self.patient1,
            doctor=self.doctor,
            title="سجل خاص",
            archive_type="visit",
            status="final",
        )

    def test_patient_cannot_access_other_patient_archive(self):
        client2 = Client()
        client2.force_login(self.user2)

        url = reverse("medical_archive:archive_detail", args=[self.archive.pk])
        response = client2.get(url)

        # حسب فيوكك: يا 403 يا 404
        self.assertIn(response.status_code, [403, 404])

    def test_patient_can_access_own_archive(self):
        client1 = Client()
        client1.force_login(self.user1)

        url = reverse("medical_archive:archive_detail", args=[self.archive.pk])
        response = client1.get(url)

        self.assertEqual(response.status_code, 200)

    def test_non_authenticated_user_cannot_access_archive(self):
        client = Client()
        url = reverse("medical_archive:archive_detail", args=[self.archive.pk])
        response = client.get(url)

        # غالباً redirect للّوگن 302، وأحياناً 403/404 حسب الإعداد
        self.assertIn(response.status_code, [302, 403, 404])

    def test_doctor_can_access_patient_archive(self):
        client_doc = Client()
        client_doc.force_login(self.doctor_user)

        url = reverse("medical_archive:archive_detail", args=[self.archive.pk])
        response = client_doc.get(url)

        self.assertEqual(response.status_code, 200)

    def test_random_user_cannot_access_any_archive(self):
        random_user = User.objects.create_user(email="random@test.com", password="pass", username="rnd")
        self._maybe_set_user_fields(random_user, role="patient", is_approved=True, is_active=True)

        client_rnd = Client()
        client_rnd.force_login(random_user)

        url = reverse("medical_archive:archive_detail", args=[self.archive.pk])
        response = client_rnd.get(url)

        self.assertIn(response.status_code, [403, 404])
