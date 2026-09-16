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


class DoctorTenantIsolationTests(TestCase):
    """
    Confirm that a doctor can access only patients connected
    to that doctor's own appointments.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Doctor Isolation Hospital A",
            code="DOC-ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a1 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Hospital A - Branch 1",
            code="DOC-ISO-A1",
            is_active=True,
        )
        self.branch_a2 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Hospital A - Branch 2",
            code="DOC-ISO-A2",
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Doctor Isolation Hospital B",
            code="DOC-ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b1 = Branch.objects.create(
            hospital=self.hospital_b,
            name="Hospital B - Branch 1",
            code="DOC-ISO-B1",
            is_active=True,
        )

        self.doctor_a1 = self._create_doctor(
            email="doctor-isolation-a1@test.com",
            username="doctor_isolation_a1",
            full_name="Doctor A1",
            hospital=self.hospital_a,
            branch=self.branch_a1,
        )
        self.doctor_a2 = self._create_doctor(
            email="doctor-isolation-a2@test.com",
            username="doctor_isolation_a2",
            full_name="Doctor A2",
            hospital=self.hospital_a,
            branch=self.branch_a2,
        )
        self.doctor_b1 = self._create_doctor(
            email="doctor-isolation-b1@test.com",
            username="doctor_isolation_b1",
            full_name="Doctor B1",
            hospital=self.hospital_b,
            branch=self.branch_b1,
        )

        self.patient_a1 = Patient.objects.create(
            full_name="Visible Doctor A1 Patient",
        )
        self.patient_a2 = Patient.objects.create(
            full_name="Hidden Branch A2 Patient",
        )
        self.patient_b1 = Patient.objects.create(
            full_name="Hidden Hospital B Patient",
        )

        base_time = timezone.now() + timedelta(days=3)

        Appointment.objects.create(
            patient=self.patient_a1,
            doctor=self.doctor_a1,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            scheduled_time=base_time,
            status=AppointmentStatus.PENDING,
            notes="DOCTOR-A1-PATIENT",
        )
        Appointment.objects.create(
            patient=self.patient_a2,
            doctor=self.doctor_a2,
            hospital=self.hospital_a,
            branch=self.branch_a2,
            scheduled_time=base_time + timedelta(hours=1),
            status=AppointmentStatus.PENDING,
            notes="DOCTOR-A2-PATIENT",
        )
        Appointment.objects.create(
            patient=self.patient_b1,
            doctor=self.doctor_b1,
            hospital=self.hospital_b,
            branch=self.branch_b1,
            scheduled_time=base_time + timedelta(hours=2),
            status=AppointmentStatus.PENDING,
            notes="DOCTOR-B1-PATIENT",
        )

        self.client.force_login(self.doctor_a1.user)

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
        apply_role_permissions(user)

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

    def test_patient_list_contains_only_own_patients(self):
        response = self.client.get(
            reverse("doctor:patients_list")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = set(
            response.context["patients"].values_list(
                "pk",
                flat=True,
            )
        )

        self.assertEqual(
            visible_ids,
            {self.patient_a1.pk},
        )

    def test_doctor_can_access_own_patient_report(self):
        response = self.client.get(
            reverse(
                "doctor:patient_report",
                args=[self.patient_a1.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_cannot_access_other_branch_patient_report(self):
        response = self.client.get(
            reverse(
                "doctor:patient_report",
                args=[self.patient_a2.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_access_other_hospital_patient_report(self):
        response = self.client.get(
            reverse(
                "doctor:patient_report",
                args=[self.patient_b1.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
