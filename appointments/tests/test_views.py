# appointments/tests/test_views.py
from datetime import timedelta

from django.forms import FileField
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import apply_role_permissions
from appointments.models import (
    Appointment,
    AppointmentStatus,
    PatientBookingRequest,
)
from hospital.models import StaffAssignment
from patient.models import Patient

from .factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    UserFactory,
)


def _model_has_field(model, field_name: str) -> bool:
    return any(
        getattr(field, "name", "") == field_name
        for field in model._meta.get_fields()
    )


def _doctor_assignment(doctor):
    return (
        StaffAssignment.objects.filter(
            user_id=doctor.user_id,
            role=StaffAssignment.Roles.DOCTOR,
            is_active=True,
        )
        .select_related(
            "hospital",
            "branch",
            "department",
        )
        .order_by("-is_primary", "pk")
        .first()
    )


def _future_datetime_input(*, days: int = 1, minutes: int = 0) -> str:
    value = timezone.localtime(
        timezone.now() + timedelta(days=days, minutes=minutes)
    )
    return value.strftime("%Y-%m-%dT%H:%M")


class BaseViewTestCase(TestCase):
    """Shared setup for authenticated secretary view tests."""

    def setUp(self):
        self.client = Client()
        self.secretary = UserFactory(
            role="secretary",
            username="sec_user",
        )
        apply_role_permissions(self.secretary)
        self.client.force_login(self.secretary)


class PermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.not_secretary = UserFactory(
            role="other",
            username="other_user",
        )
        self.client.force_login(self.not_secretary)

    def test_secretary_dashboard_forbidden_if_not_secretary(self):
        url = reverse("appointments:secretary_dashboard")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_secretary_dashboard_requires_login(self):
        self.client.logout()
        url = reverse("appointments:secretary_dashboard")
        response = self.client.get(url)

        self.assertIn(response.status_code, (301, 302))
        self.assertIn("login", response.url.lower())


class SecretaryDashboardTests(BaseViewTestCase):
    def test_dashboard_renders(self):
        url = reverse("appointments:secretary_dashboard")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Weekly Patients Overview")

    def test_dashboard_stats_counts(self):
        doctor = DoctorFactory()
        patient = PatientFactory()
        AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        url = reverse("appointments:secretary_dashboard")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("stats", response.context)
        self.assertIsInstance(
            response.context["stats"]["appointments_today"],
            int,
        )


class CreateAppointmentViewTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()
        self.assignment = _doctor_assignment(self.doctor)
        self.url = reverse("appointments:create_appointment")

    def _valid_payload(self):
        self.assertIsNotNone(
            self.assignment,
            "DoctorFactory must create an active doctor assignment.",
        )

        return {
            "patient": self.patient.pk,
            "hospital": self.assignment.hospital_id,
            "branch": self.assignment.branch_id or "",
            "department": self.assignment.department_id or "",
            "doctor": self.doctor.pk,
            "scheduled_time": _future_datetime_input(days=1),
            "status": AppointmentStatus.PENDING,
            "iqd_amount": 10000,
            "notes": "Created by the appointment view test.",
        }

    def test_get_create_appointment_form(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<form")

    def test_post_create_valid_appointment(self):
        response = self.client.post(
            self.url,
            self._valid_payload(),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Appointment.objects.filter(
                doctor=self.doctor,
                patient=self.patient,
            ).exists()
        )

        appointment = Appointment.objects.get(
            doctor=self.doctor,
            patient=self.patient,
        )
        self.assertEqual(
            appointment.hospital_id,
            self.assignment.hospital_id,
        )
        self.assertEqual(
            appointment.branch_id,
            self.assignment.branch_id,
        )
        self.assertEqual(
            appointment.department_id,
            self.assignment.department_id,
        )

    def test_post_create_invalid_missing_required(self):
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.errors)
        self.assertIn("patient", form.errors)
        self.assertIn("doctor", form.errors)
        self.assertIn("scheduled_time", form.errors)


class AppointmentListViewTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient_one = PatientFactory(
            full_name="Alpha Patient",
        )
        self.patient_two = PatientFactory(
            full_name="Beta Patient",
        )

        AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient_one,
            scheduled_time=timezone.now() + timedelta(minutes=10),
            queue_number=1,
        )
        AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient_two,
            scheduled_time=timezone.now() + timedelta(minutes=20),
            queue_number=2,
        )
        self.url = reverse("appointments:appointment_list")

    def test_list_default(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Patient")
        self.assertContains(response, "Beta Patient")

    def test_search_patient_name(self):
        response = self.client.get(
            self.url,
            {"q": "Alpha"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Patient")
        self.assertNotContains(response, "Beta Patient")

    def test_sort_by_patient(self):
        response = self.client.get(
            self.url,
            {"sort": "patient"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Patient")
        self.assertContains(response, "Beta Patient")


class PatientPortalBookingViewTests(TestCase):
    """Tests for the current logged-in patient booking workflow."""

    def setUp(self):
        self.client = Client()
        self.doctor = DoctorFactory()
        self.patient_user = UserFactory(
            role="patient",
            username="patient_portal_user",
        )

        if _model_has_field(Patient, "user"):
            self.patient = Patient.objects.filter(
                user=self.patient_user
            ).first()

            if self.patient is None:
                self.patient = PatientFactory(
                    user=self.patient_user,
                    full_name="Portal Patient",
                )
        else:
            self.patient = PatientFactory(
                full_name="Portal Patient",
            )
        self.url = reverse(
            "appointments:book_patient",
            args=[self.doctor.pk],
        )

    def test_booking_requires_login(self):
        response = self.client.get(self.url)

        self.assertIn(response.status_code, (301, 302))
        self.assertIn("login", response.url.lower())

    def test_non_patient_user_is_forbidden(self):
        secretary = UserFactory(
            role="secretary",
            username="booking_secretary",
        )
        self.client.force_login(secretary)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_get_booking_form_for_patient(self):
        self.client.force_login(self.patient_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<form")
        self.assertEqual(response.context["doctor"], self.doctor)
        self.assertEqual(response.context["patient"], self.patient)

    def test_post_valid_booking_request(self):
        self.client.force_login(self.patient_user)

        response = self.client.post(
            self.url,
            {
                "scheduled_time": _future_datetime_input(days=2),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            PatientBookingRequest.objects.filter(
                doctor=self.doctor,
                full_name=self.patient.full_name,
            ).exists()
        )


class APIsTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()

        self.appointment_one = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            queue_number=1,
        )
        self.appointment_two = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=15),
            queue_number=2,
        )
        self.appointment_three = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=25),
            queue_number=3,
        )

    def test_new_booking_requests_api_empty(self):
        url = reverse("appointments:new_booking_requests_api")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("booking_requests", data)
        self.assertEqual(data["count"], 0)

    def test_queue_number_api_structure(self):
        url = reverse("appointments:queue_number_api")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("queues", data)
        self.assertGreaterEqual(len(data["queues"]), 1)

    def test_current_patient_api(self):
        url = reverse("appointments:current_patient_api")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("current_patient", data)
        self.assertIn("next_patient", data)

    def test_call_next_api_marks_completed(self):
        url = reverse(
            "appointments:call_next_api",
            args=[self.doctor.pk],
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("success"))

        self.appointment_one.refresh_from_db()
        self.assertEqual(
            self.appointment_one.status,
            AppointmentStatus.COMPLETED,
        )

    def test_call_next_api_until_empty(self):
        url = reverse(
            "appointments:call_next_api",
            args=[self.doctor.pk],
        )

        self.client.post(url)
        self.client.post(url)
        self.client.post(url)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)


class SettingsViewTests(BaseViewTestCase):
    def test_settings_get(self):
        url = reverse("appointments:secretary_settings")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settings")
        self.assertIn("profile_form", response.context)
        self.assertIn("password_form", response.context)

    def test_settings_post_profile(self):
        url = reverse("appointments:secretary_settings")
        get_response = self.client.get(url)
        profile_form = get_response.context["profile_form"]

        payload = {
            "form_type": "profile",
        }

        for name, field in profile_form.fields.items():
            if isinstance(field, FileField):
                continue

            value = profile_form[name].value()

            if value is None or value is False:
                continue

            if value is True:
                payload[name] = "on"
            else:
                payload[name] = value

        if "first_name" in profile_form.fields:
            payload["first_name"] = "Updated"
        elif "full_name" in profile_form.fields:
            payload["full_name"] = "Updated Secretary"
        elif "email" in profile_form.fields:
            payload["email"] = "updated.secretary@example.com"

        response = self.client.post(
            url,
            payload,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        response_messages = list(response.context["messages"])
        self.assertTrue(
            any("success" in message.tags for message in response_messages),
            "Expected a success message after saving the profile form.",
        )
