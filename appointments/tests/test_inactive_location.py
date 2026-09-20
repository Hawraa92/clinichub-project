from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from appointments.forms import AppointmentForm
from appointments.models import AppointmentStatus
from appointments.tests.factories import (
    DoctorFactory,
    PatientFactory,
    get_doctor_assignment,
)


class InactiveAppointmentLocationTests(TestCase):
    def test_appointment_form_rejects_inactive_hospital(self):
        doctor = DoctorFactory()
        patient = PatientFactory()
        assignment = get_doctor_assignment(doctor)

        hospital = assignment.hospital
        hospital.is_active = False
        hospital.save(update_fields=["is_active"])

        scheduled_time = timezone.now() + timedelta(days=1)

        form = AppointmentForm(
            data={
                "patient": patient.pk,
                "doctor": doctor.pk,
                "hospital": hospital.pk,
                "branch": assignment.branch_id,
                "department": assignment.department_id,
                "scheduled_time": scheduled_time.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "status": AppointmentStatus.PENDING,
                "iqd_amount": "0",
            }
        )

        self.assertFalse(
            form.is_valid(),
            msg=(
                "AppointmentForm accepted an inactive hospital. "
                f"Errors: {form.errors.as_json()}"
            ),
        )
        self.assertIn("hospital", form.errors)

    def test_appointment_form_rejects_inactive_branch(self):
        doctor = DoctorFactory()
        patient = PatientFactory()
        assignment = get_doctor_assignment(doctor)

        branch = assignment.branch
        branch.is_active = False
        branch.save(update_fields=["is_active"])

        scheduled_time = timezone.now() + timedelta(days=1)

        form = AppointmentForm(
            data={
                "patient": patient.pk,
                "doctor": doctor.pk,
                "hospital": assignment.hospital_id,
                "branch": branch.pk,
                "department": assignment.department_id,
                "scheduled_time": scheduled_time.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "status": AppointmentStatus.PENDING,
                "iqd_amount": "0",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("branch", form.errors)

    def test_appointment_form_rejects_inactive_department(self):
        doctor = DoctorFactory()
        patient = PatientFactory()
        assignment = get_doctor_assignment(doctor)

        department = assignment.department
        department.is_active = False
        department.save(update_fields=["is_active"])

        scheduled_time = timezone.now() + timedelta(days=1)

        form = AppointmentForm(
            data={
                "patient": patient.pk,
                "doctor": doctor.pk,
                "hospital": assignment.hospital_id,
                "branch": assignment.branch_id,
                "department": department.pk,
                "scheduled_time": scheduled_time.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "status": AppointmentStatus.PENDING,
                "iqd_amount": "0",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)