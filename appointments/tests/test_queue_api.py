# appointments/tests/test_queue_api.py
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import apply_role_permissions
from appointments.models import AppointmentStatus

from .factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    UserFactory,
)


class QueueAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.secretary = UserFactory(
            role="secretary",
            username="queue_secretary",
        )
        apply_role_permissions(self.secretary)
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()
        self.client.force_login(self.secretary)
        self.url = reverse("appointments:queue_number_api")

    def test_queue_number_api_empty(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("queues", data)
        self.assertIsInstance(data["queues"], list)

    def test_queue_number_api_with_appointment(self):
        appointment = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            status=AppointmentStatus.PENDING,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data["queues"])

        queue = next(
            (
                item
                for item in data["queues"]
                if item["doctor_id"] == self.doctor.pk
            ),
            None,
        )

        self.assertIsNotNone(queue)
        visible_ids = []

        current = queue.get("current")
        if current:
            visible_ids.append(current["id"])

        visible_ids.extend(
            item["id"]
            for item in queue.get("waiting", [])
        )

        self.assertIn(appointment.pk, visible_ids)

        self.assertEqual(
            current["patient_name"] if current else None,
            self.patient.full_name,
        )
