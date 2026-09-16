from datetime import date, timedelta

from appointments.models import Appointment
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from doctor.models import Doctor
from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient
from prescription.models import Medication, Prescription

from pharmacy.models import (
    Pharmacy,
    PharmacyOrder,
    PharmacyStaffAssignment,
)
from pharmacy.services import send_prescription_to_pharmacy
from pharmacy.test_permission_utils import (
    apply_role_permissions,
)


User = get_user_model()


class PharmacyOrderTenantIsolationTests(TestCase):
    """
    A pharmacist may see and process orders belonging only
    to pharmacies assigned to that pharmacist.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Order Isolation Hospital A",
            code="ORD-ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Order Branch A",
            code="ORD-ISO-A",
            is_active=True,
        )
        self.pharmacy_a = Pharmacy.objects.create(
            branch=self.branch_a,
            name="Assigned Order Pharmacy A",
            code="ORD-PH-A",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Order Isolation Hospital B",
            code="ORD-ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Order Branch B",
            code="ORD-ISO-B",
            is_active=True,
        )
        self.pharmacy_b = Pharmacy.objects.create(
            branch=self.branch_b,
            name="Foreign Order Pharmacy B",
            code="ORD-PH-B",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.pharmacist_a = self._create_pharmacist(
            email="order-pharmacist-a@test.com",
            pharmacy=self.pharmacy_a,
            hospital=self.hospital_a,
            branch=self.branch_a,
        )
        self.pharmacist_b = self._create_pharmacist(
            email="order-pharmacist-b@test.com",
            pharmacy=self.pharmacy_b,
            hospital=self.hospital_b,
            branch=self.branch_b,
        )

        (
            self.doctor_a,
            self.prescription_a,
        ) = self._create_prescription(
            suffix="a",
            hospital=self.hospital_a,
            branch=self.branch_a,
            patient_name="Visible Order Patient A",
        )

        (
            self.doctor_b,
            self.prescription_b,
        ) = self._create_prescription(
            suffix="b",
            hospital=self.hospital_b,
            branch=self.branch_b,
            patient_name="Hidden Order Patient B",
        )

        self.order_a = send_prescription_to_pharmacy(
            prescription=self.prescription_a,
            pharmacy=self.pharmacy_a,
            sent_by=self.doctor_a.user,
        )
        self.order_b = send_prescription_to_pharmacy(
            prescription=self.prescription_b,
            pharmacy=self.pharmacy_b,
            sent_by=self.doctor_b.user,
        )

        self.foreign_order_item = self.order_b.items.first()
        self.client.force_login(self.pharmacist_a)

    def _create_pharmacist(
        self,
        *,
        email,
        pharmacy,
        hospital,
        branch,
    ):
        user = User.objects.create_user(
            email=email,
            password=self.password,
            role="pharmacist",
            is_approved=True,
        )
        apply_role_permissions(user)

        assignment = StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )

        PharmacyStaffAssignment.objects.create(
            pharmacy=pharmacy,
            staff_assignment=assignment,
            is_manager=True,
            is_active=True,
        )

        return user

    def _create_prescription(
        self,
        *,
        suffix,
        hospital,
        branch,
        patient_name,
    ):
        doctor_user = User.objects.create_user(
            email=f"order-doctor-{suffix}@test.com",
            password=self.password,
            role="doctor",
            is_approved=True,
        )
        apply_role_permissions(doctor_user)

        doctor = Doctor.objects.create(
            user=doctor_user,
            full_name=f"Order Doctor {suffix.upper()}",
            specialty="General",
        )

        StaffAssignment.objects.create(
            user=doctor_user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        patient_user = User.objects.create_user(
            email=f"order-patient-{suffix}@test.com",
            password=self.password,
            role="patient",
            is_approved=True,
        )

        patient, _created = Patient.objects.get_or_create(
            user=patient_user,
            defaults={
                "full_name": patient_name,
                "date_of_birth": date(1990, 1, 1),
            },
        )

        patient.full_name = patient_name
        patient.date_of_birth = date(1990, 1, 1)
        patient.save()

        appointment = Appointment.objects.create(
            doctor=doctor,
            patient=patient,
            hospital=hospital,
            branch=branch,
            scheduled_time=(
                timezone.now()
                + timedelta(days=2)
            ),
        )

        prescription = Prescription.objects.create(
            appointment=appointment,
            patient=patient,
            doctor=doctor,
            patient_full_name=patient.full_name,
            age=36,
            diagnosis=f"Order isolation diagnosis {suffix}",
        )

        Medication.objects.create(
            prescription=prescription,
            name=f"Medicine {suffix.upper()}",
            dosage="One tablet daily",
        )

        return doctor, prescription

    def test_order_list_contains_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:orders")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            order.pk
            for order
            in response.context["page_obj"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.order_a.pk},
        )

    def test_can_open_assigned_pharmacy_order(self):
        response = self.client.get(
            reverse(
                "pharmacy:order_detail",
                kwargs={"pk": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_cannot_open_foreign_pharmacy_order(self):
        response = self.client.get(
            reverse(
                "pharmacy:order_detail",
                kwargs={"pk": self.order_b.pk},
            )
        )

        self.assertIn(
            response.status_code,
            (403, 404),
        )

    def test_cannot_accept_foreign_pharmacy_order(self):
        original_status = self.order_b.status

        response = self.client.post(
            reverse(
                "pharmacy:accept_order",
                kwargs={"pk": self.order_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

        self.order_b.refresh_from_db()
        self.assertEqual(
            self.order_b.status,
            original_status,
        )

    def test_cannot_dispense_foreign_pharmacy_order(self):
        response = self.client.get(
            reverse(
                "pharmacy:dispense_order",
                kwargs={"pk": self.order_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_assign_foreign_order_item(self):
        self.assertIsNotNone(self.foreign_order_item)

        response = self.client.get(
            reverse(
                "pharmacy:assign_order_item",
                kwargs={
                    "item_id": self.foreign_order_item.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)
