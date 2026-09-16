from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import (
    apply_role_permissions,
)
from appointments.models import (
    Appointment,
    AppointmentStatus,
)
from doctor.models import Doctor
from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient


User = get_user_model()


class AppointmentTenantIsolationTests(TestCase):
    """
    Verify that a secretary assigned to one branch cannot view,
    edit, delete, or create appointments in another branch or hospital.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        # Hospital A with two separate branches.
        self.hospital_a = Hospital.objects.create(
            name="Isolation Hospital A",
            code="ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a1 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Hospital A - Branch 1",
            code="ISO-A1",
            is_active=True,
        )
        self.branch_a2 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Hospital A - Branch 2",
            code="ISO-A2",
            is_active=True,
        )

        # Completely separate hospital.
        self.hospital_b = Hospital.objects.create(
            name="Isolation Hospital B",
            code="ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b1 = Branch.objects.create(
            hospital=self.hospital_b,
            name="Hospital B - Branch 1",
            code="ISO-B1",
            is_active=True,
        )

        # Secretary belongs only to Hospital A / Branch 1.
        self.secretary = User.objects.create_user(
            email="isolation-secretary@test.com",
            username="isolation_secretary",
            password=self.password,
            role="secretary",
            is_approved=True,
        )
        apply_role_permissions(self.secretary)

        StaffAssignment.objects.create(
            user=self.secretary,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            role=StaffAssignment.Roles.SECRETARY,
            is_primary=True,
            is_active=True,
        )

        self.doctor_a1 = self._create_doctor(
            email="doctor-a1@test.com",
            username="doctor_a1",
            full_name="Doctor Branch A1",
            hospital=self.hospital_a,
            branch=self.branch_a1,
        )
        self.doctor_a2 = self._create_doctor(
            email="doctor-a2@test.com",
            username="doctor_a2",
            full_name="Doctor Branch A2",
            hospital=self.hospital_a,
            branch=self.branch_a2,
        )
        self.doctor_b1 = self._create_doctor(
            email="doctor-b1@test.com",
            username="doctor_b1",
            full_name="Doctor Hospital B",
            hospital=self.hospital_b,
            branch=self.branch_b1,
        )

        self.patient_a1 = Patient.objects.create(
            full_name="Visible Patient A1",
        )
        self.patient_a2 = Patient.objects.create(
            full_name="Hidden Patient A2",
        )
        self.patient_b1 = Patient.objects.create(
            full_name="Hidden Patient B1",
        )

        base_time = timezone.now() + timedelta(days=3)

        self.appointment_a1 = Appointment.objects.create(
            patient=self.patient_a1,
            doctor=self.doctor_a1,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            scheduled_time=base_time,
            status=AppointmentStatus.PENDING,
            notes="VISIBLE-APPOINTMENT-A1",
        )
        self.appointment_a2 = Appointment.objects.create(
            patient=self.patient_a2,
            doctor=self.doctor_a2,
            hospital=self.hospital_a,
            branch=self.branch_a2,
            scheduled_time=base_time + timedelta(hours=1),
            status=AppointmentStatus.PENDING,
            notes="HIDDEN-APPOINTMENT-A2",
        )
        self.appointment_b1 = Appointment.objects.create(
            patient=self.patient_b1,
            doctor=self.doctor_b1,
            hospital=self.hospital_b,
            branch=self.branch_b1,
            scheduled_time=base_time + timedelta(hours=2),
            status=AppointmentStatus.PENDING,
            notes="HIDDEN-APPOINTMENT-B1",
        )

        self.client.force_login(self.secretary)

    def _create_doctor(
        self,
        *,
        email,
        username,
        full_name,
        hospital,
        branch,
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=self.password,
            role="doctor",
            is_approved=True,
        )

        doctor = Doctor.objects.create(
            user=user,
            full_name=full_name,
            specialty="General",
        )

        StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        return doctor

    def test_list_contains_only_assigned_branch_appointments(self):
        response = self.client.get(
            reverse("appointments:appointment_list")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            appointment.pk
            for appointment in response.context["appointments"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.appointment_a1.pk},
        )

    def test_cannot_edit_appointment_from_other_branch(self):
        response = self.client.get(
            reverse(
                "appointments:edit_appointment",
                args=[self.appointment_a2.pk],
            )
        )

        # Return 404 so the foreign record is not disclosed.
        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_appointment_from_other_hospital(self):
        response = self.client.post(
            reverse(
                "appointments:delete_appointment",
                args=[self.appointment_b1.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

        self.assertTrue(
            Appointment.objects.filter(
                pk=self.appointment_b1.pk
            ).exists()
        )

    def test_cannot_create_appointment_in_other_branch(self):
        before_count = Appointment.objects.count()

        future_time = timezone.localtime(
            timezone.now() + timedelta(days=5)
        ).strftime("%Y-%m-%dT%H:%M")

        response = self.client.post(
            reverse("appointments:create_appointment"),
            {
                "patient": self.patient_a2.pk,
                "hospital": self.hospital_a.pk,
                "branch": self.branch_a2.pk,
                "department": "",
                "doctor": self.doctor_a2.pk,
                "scheduled_time": future_time,
                "iqd_amount": 0,
                "status": AppointmentStatus.PENDING,
                "notes": "ILLEGAL-CROSS-BRANCH-CREATE",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Appointment.objects.count(),
            before_count,
        )
        self.assertFalse(
            Appointment.objects.filter(
                notes="ILLEGAL-CROSS-BRANCH-CREATE"
            ).exists()
        )
