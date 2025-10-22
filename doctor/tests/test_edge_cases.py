# doctor/tests/test_edge_cases.py
from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment

User = get_user_model()
PASSWORD = "pass1234"


class DoctorEdgeCaseTest(TestCase):
    def setUp(self):
        # ----- Doctor & Login -----
        self.doctor_user = User.objects.create_user(
            email="edge@clinic.com", password=PASSWORD, role="doctor"
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Edge",
            specialty="General",        # ← مضاف
        )
        self.client.login(email="edge@clinic.com", password=PASSWORD)

        # ----- Patients with غريب أسماء -----
        self.patient_empty = Patient.objects.create(full_name="Unknown")
        self.patient_long = Patient.objects.create(full_name="A" * 100)
        self.patient_unicode = Patient.objects.create(full_name="حُسَين-Женя-😊-123")
        self.patient_numbers = Patient.objects.create(full_name="1234567890")
        self.patient_weird = Patient.objects.create(
            full_name="Robert'); DROP TABLE Patients;--"
        )

        # ----- مواعيد مستقبلية -----
        base_time = timezone.now() + timedelta(days=1)
        for i, p in enumerate(
            [
                self.patient_long,
                self.patient_unicode,
                self.patient_weird,
                self.patient_numbers,
            ]
        ):
            Appointment.objects.create(
                patient=p,
                doctor=self.doctor,
                scheduled_time=base_time + timedelta(minutes=10 * i),
            )

    # ----------------------- الاختبارات ----------------------- #
    def test_search_empty_query_returns_all(self):
        resp = self.client.get(reverse("doctor:patient_search") + "?q=")
        self.assertContains(resp, "A" * 100)
        self.assertContains(resp, "1234567890")
        self.assertContains(resp, "حُسَين-Женя-😊-123")

    def test_search_long_name(self):
        resp = self.client.get(
            reverse("doctor:patient_search") + "?q=" + "A" * 50
        )
        self.assertContains(resp, "A" * 100)

    def test_search_unicode_name(self):
        resp = self.client.get(reverse("doctor:patient_search") + "?q=Женя")
        self.assertContains(resp, "حُسَين-Женя-😊-123")

    def test_search_numbers_only(self):
        resp = self.client.get(reverse("doctor:patient_search") + "?q=1234567890")
        self.assertContains(resp, "1234567890")

    def test_search_sql_injection_like(self):
        resp = self.client.get(reverse("doctor:patient_search") + "?q=DROP TABLE")
        self.assertContains(resp, "Robert&#x27;); DROP TABLE Patients;--")
