# prescription/tests/test_constraints.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from .factories import make_doctor, make_patient, make_appointment
from prescription.models import Prescription


@override_settings(SITE_URL="http://testserver")
class TestPrescriptionConstraints(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doctor = make_doctor(email="doc_cons@x.com")
        cls.patient = make_patient(full_name="Constraint Patient", email="pat_cons@x.com")
        cls.appt = make_appointment(cls.doctor, cls.patient)

    def test_unique_prescription_per_appointment(self):
        # First RX should be created successfully
        p1 = Prescription.objects.create(
            appointment=self.appt,
            doctor=self.appt.doctor,
            patient=self.appt.patient,
            patient_full_name=self.appt.patient.full_name,
            age=30,
        )
        self.assertIsNotNone(p1.pk)

        # Second RX for same appointment must fail.
        # In this codebase Prescription.save() calls full_clean(),
        # so the duplicate may raise ValidationError before hitting DB constraint.
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                Prescription.objects.create(
                    appointment=self.appt,
                    doctor=self.appt.doctor,
                    patient=self.appt.patient,
                    patient_full_name=self.appt.patient.full_name,
                    age=30,
                )