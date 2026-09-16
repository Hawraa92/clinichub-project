# appointments/tests/test_secretary_views.py
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import apply_role_permissions
from appointments.models import Appointment, AppointmentStatus
from hospital.models import StaffAssignment

from .factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    UserFactory,
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


def _future_datetime_input(days: int = 1, hours: int = 0) -> str:
    value = timezone.localtime(
        timezone.now() + timedelta(days=days, hours=hours)
    )
    return value.strftime("%Y-%m-%dT%H:%M")


class SecretaryViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.secretary = UserFactory(
            role="secretary",
            username="secretary_views_user",
        )
        apply_role_permissions(self.secretary)
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()
        self.assignment = _doctor_assignment(self.doctor)

        self.assertIsNotNone(
            self.assignment,
            "DoctorFactory must create an active doctor assignment.",
        )

    def _login_secretary(self):
        self.client.force_login(self.secretary)

    def _appointment_payload(
        self,
        *,
        scheduled_time: str,
        status=AppointmentStatus.PENDING,
    ):
        return {
            "patient": self.patient.pk,
            "hospital": self.assignment.hospital_id,
            "branch": self.assignment.branch_id or "",
            "department": self.assignment.department_id or "",
            "doctor": self.doctor.pk,
            "scheduled_time": scheduled_time,
            "iqd_amount": 0,
            "status": status,
            "notes": "Secretary view test.",
        }

    def test_secretary_dashboard_requires_role(self):
        url = reverse("appointments:secretary_dashboard")

        anonymous_response = self.client.get(url)
        self.assertIn(
            anonymous_response.status_code,
            (301, 302),
        )

        self._login_secretary()
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("stats", response.context)

    def test_create_appointment_success(self):
        self._login_secretary()

        response = self.client.post(
            reverse("appointments:create_appointment"),
            self._appointment_payload(
                scheduled_time=_future_datetime_input(days=1),
            ),
        )

        self.assertIn(response.status_code, (301, 302, 303))
        self.assertTrue(
            Appointment.objects.filter(
                doctor=self.doctor,
                patient=self.patient,
            ).exists()
        )

    def test_edit_appointment(self):
        self._login_secretary()
        appointment = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(days=1),
        )
        new_time = _future_datetime_input(days=2)

        response = self.client.post(
            reverse(
                "appointments:edit_appointment",
                args=[appointment.pk],
            ),
            self._appointment_payload(
                scheduled_time=new_time,
                status=appointment.status,
            ),
        )

        self.assertIn(response.status_code, (301, 302, 303))

        appointment.refresh_from_db()
        expected = timezone.make_aware(
            timezone.datetime.strptime(
                new_time,
                "%Y-%m-%dT%H:%M",
            ),
            timezone.get_current_timezone(),
        )

        self.assertEqual(
            timezone.localtime(appointment.scheduled_time).replace(
                second=0,
                microsecond=0,
            ),
            expected.replace(
                second=0,
                microsecond=0,
            ),
        )

    def test_delete_appointment_moves_to_recycle_bin(self):
        self._login_secretary()
        appointment = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(days=1),
        )

        response = self.client.post(
            reverse(
                "appointments:delete_appointment",
                args=[appointment.pk],
            )
        )

        self.assertIn(response.status_code, (301, 302, 303))
        self.assertFalse(
            Appointment.objects.filter(pk=appointment.pk).exists()
        )
        self.assertTrue(
            Appointment.deleted_objects.filter(
                pk=appointment.pk
            ).exists()
        )
