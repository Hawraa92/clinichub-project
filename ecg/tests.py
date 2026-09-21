from django.core.exceptions import ValidationError
from django.test import TestCase

from appointments.tests.factories import (
    AppointmentFactory,
    BranchFactory,
    DepartmentFactory,
    HospitalFactory,
    PatientFactory,
)
from ecg.models import ECGRecord


class ECGRecordValidationTests(TestCase):
    def test_valid_record_matches_appointment(self):
        appointment = AppointmentFactory()

        record = ECGRecord(
            patient=appointment.patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        record.full_clean()

    def test_rejects_patient_different_from_appointment(self):
        appointment = AppointmentFactory()
        other_patient = PatientFactory()

        record = ECGRecord(
            patient=other_patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        self.assertIn("patient", context.exception.message_dict)

    def test_rejects_doctor_different_from_appointment(self):
        appointment = AppointmentFactory()
        other_appointment = AppointmentFactory()

        record = ECGRecord(
            patient=appointment.patient,
            doctor=other_appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        self.assertIn("doctor", context.exception.message_dict)

    def test_rejects_location_different_from_appointment(self):
        appointment = AppointmentFactory()

        other_hospital = HospitalFactory(
            code="ECG-OTHER-HOSPITAL",
            name="ECG Other Hospital",
        )
        other_branch = BranchFactory(
            hospital=other_hospital,
            code="ECG-OTHER-BRANCH",
            name="ECG Other Branch",
        )
        other_department = DepartmentFactory(
            branch=other_branch,
            code="ECG-OTHER-DEPARTMENT",
            name="ECG Other Department",
        )

        record = ECGRecord(
            patient=appointment.patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=other_hospital,
            branch=other_branch,
            department=other_department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        errors = context.exception.message_dict

        self.assertTrue(
            any(
                field in errors
                for field in ("hospital", "branch", "department")
            )
        )