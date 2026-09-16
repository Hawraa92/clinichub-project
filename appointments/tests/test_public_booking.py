# appointments/tests/test_public_booking.py
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from appointments.models import (
    Appointment,
    AppointmentStatus,
    PatientBookingRequest,
)
from patient.models import Patient

from .factories import (
    DoctorFactory,
    PatientFactory,
    UserFactory,
    get_doctor_assignment,
)


def _model_has_field(model, field_name: str) -> bool:
    return any(
        getattr(field, "name", "") == field_name
        for field in model._meta.get_fields()
    )


def _future_datetime_input(days: int = 2) -> str:
    value = timezone.localtime(
        timezone.now() + timedelta(days=days)
    )
    return value.strftime("%Y-%m-%dT%H:%M")


class PublicBookingTests(TestCase):
    """Tests for public queue pages and the current patient booking flow."""

    def setUp(self):
        self.client = Client()
        self.doctor = DoctorFactory()
        self.patient_user = UserFactory(
            role="patient",
            username="public_booking_patient",
        )

        if _model_has_field(Patient, "user"):
            self.patient = Patient.objects.filter(
                user=self.patient_user
            ).first()

            if self.patient is None:
                self.patient = PatientFactory(
                    user=self.patient_user,
                    full_name="Public Booking Patient",
                )
        else:
            self.patient = PatientFactory(
                full_name="Public Booking Patient",
            )

        self.booking_url = reverse(
            "appointments:book_patient",
            args=[self.doctor.pk],
        )

    def test_get_public_queue_page(self):
        response = self.client.get(
            reverse("appointments:queue_display")
        )

        self.assertEqual(response.status_code, 200)

    def test_get_public_queue_api(self):
        response = self.client.get(
            reverse("appointments:queue_public_api")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("queues", data)

    def test_public_queue_html_does_not_expose_patient_name(self):
        appointment = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            status=AppointmentStatus.PENDING,
        )

        response = self.client.get(
            reverse("appointments:queue_display")
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.patient.full_name)

    def test_public_queue_json_does_not_expose_patient_name(self):
        appointment = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            status=AppointmentStatus.PENDING,
        )

        response = self.client.get(
            reverse("appointments:queue_public_api")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn(self.patient.full_name, str(data))

        queue = next(
            item for item in data["queues"]
            if item["doctor_id"] == self.doctor.pk
        )
        self.assertNotIn("patient_name", queue["current"] or {})
        self.assertIn("number", queue["current"] or {})
        self.assertNotIn("id", queue["current"] or {})
        for waiting in queue["waiting"]:
            self.assertNotIn("patient_name", waiting)
            self.assertIn("number", waiting)
            self.assertNotIn("id", waiting)
        self.assertEqual(
            queue["current"]["number"],
            f"P-{appointment.queue_number:03d}",
        )

    def test_public_queue_filters_remain_privacy_safe(self):
        assignment = get_doctor_assignment(self.doctor)
        appointment = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            hospital=assignment.hospital,
            branch=assignment.branch,
            department=assignment.department,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            status=AppointmentStatus.PENDING,
        )

        for query in (
            f"?hospital={assignment.hospital_id}",
            f"?branch={assignment.branch_id}",
            f"?department={assignment.department_id}",
        ):
            response = self.client.get(
                reverse("appointments:queue_public_api") + query
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotIn(self.patient.full_name, str(data))

            queue = next(
                item for item in data["queues"]
                if item["doctor_id"] == self.doctor.pk
            )
            items = [queue["current"]] + queue["waiting"]
            self.assertTrue(any(item and item.get("number") for item in items))
            for item in items:
                if not item:
                    continue
                for forbidden in (
                    "id",
                    "patient_id",
                    "patient_name",
                    "phone",
                    "notes",
                    "diagnosis",
                    "reason",
                ):
                    self.assertNotIn(forbidden, item)

    def test_booking_page_requires_login(self):
        response = self.client.get(self.booking_url)

        self.assertIn(response.status_code, (301, 302))
        self.assertIn("login", response.url.lower())

    def test_booking_page_rejects_non_patient(self):
        secretary = UserFactory(
            role="secretary",
            username="public_booking_secretary",
        )
        self.client.force_login(secretary)

        response = self.client.get(self.booking_url)

        self.assertEqual(response.status_code, 403)

    def test_get_patient_booking_page(self):
        self.client.force_login(self.patient_user)

        response = self.client.get(self.booking_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<form")
        self.assertEqual(response.context["doctor"], self.doctor)
        self.assertEqual(response.context["patient"], self.patient)

    def test_post_invalid_booking_does_not_create_record(self):
        self.client.force_login(self.patient_user)

        before_requests = PatientBookingRequest.objects.count()
        before_appointments = Appointment.objects.count()

        response = self.client.post(
            self.booking_url,
            {},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PatientBookingRequest.objects.count(),
            before_requests,
        )
        self.assertEqual(
            Appointment.objects.count(),
            before_appointments,
        )
        self.assertTrue(response.context["form"].errors)

    def test_post_valid_booking_creates_request_or_appointment(self):
        self.client.force_login(self.patient_user)

        before_requests = PatientBookingRequest.objects.count()
        before_appointments = Appointment.objects.count()

        response = self.client.post(
            self.booking_url,
            {
                "scheduled_time": _future_datetime_input(),
            },
        )

        self.assertIn(response.status_code, (301, 302))

        created_request = (
            PatientBookingRequest.objects.count()
            == before_requests + 1
        )
        created_appointment = (
            Appointment.objects.count()
            == before_appointments + 1
        )

        self.assertTrue(
            created_request or created_appointment,
            "Expected a booking request or pending appointment to be created.",
        )
