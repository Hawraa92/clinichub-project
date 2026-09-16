from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import apply_role_permissions
from appointments.models import Appointment
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient

from .models import LabOrder, LabResult


PASSWORD = "pass1234"


class LabTenantIsolationTests(TestCase):
    def setUp(self):
        self.hospital_a = Hospital.objects.create(name="Hospital A", code="HA")
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Branch A",
            code="A",
        )
        self.branch_a2 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Branch A2",
            code="A2",
        )
        self.hospital_b = Hospital.objects.create(name="Hospital B", code="HB")
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Branch B",
            code="B",
        )

        self.lab_a = self._user("lab-a@example.com", "lab")
        self.lab_b = self._user("lab-b@example.com", "lab")
        self.doctor_user_a = self._user("doctor-a@example.com", "doctor")
        self.doctor_user_a2 = self._user("doctor-a2@example.com", "doctor")
        self.doctor_user_b = self._user("doctor-b@example.com", "doctor")

        self.doctor_a = Doctor.objects.create(
            user=self.doctor_user_a,
            full_name="Doctor A",
        )
        self.doctor_a2 = Doctor.objects.create(
            user=self.doctor_user_a2,
            full_name="Doctor A2",
        )
        self.doctor_b = Doctor.objects.create(
            user=self.doctor_user_b,
            full_name="Doctor B",
        )

        self._assign(
            self.lab_a,
            StaffAssignment.Roles.LAB_TECHNICIAN,
            self.hospital_a,
            self.branch_a,
        )
        self._assign(
            self.lab_b,
            StaffAssignment.Roles.LAB_TECHNICIAN,
            self.hospital_b,
            self.branch_b,
        )
        self._assign(
            self.doctor_user_a,
            StaffAssignment.Roles.DOCTOR,
            self.hospital_a,
            self.branch_a,
        )
        self._assign(
            self.doctor_user_a2,
            StaffAssignment.Roles.DOCTOR,
            self.hospital_a,
            self.branch_a2,
        )
        self._assign(
            self.doctor_user_b,
            StaffAssignment.Roles.DOCTOR,
            self.hospital_b,
            self.branch_b,
        )

        self.patient_a = Patient.objects.create(
            full_name="Patient Alpha",
            mobile="+9647701234567",
            doctor=self.doctor_a,
        )
        self.patient_a_other = Patient.objects.create(
            full_name="Patient Same Branch",
            mobile="+9647701234568",
            doctor=self.doctor_a,
        )
        self.patient_a2 = Patient.objects.create(
            full_name="Patient Other Branch",
            mobile="+9647701234569",
            doctor=self.doctor_a2,
        )
        self.patient_b = Patient.objects.create(
            full_name="Patient Beta Secret",
            mobile="+9647701234570",
            doctor=self.doctor_b,
        )

        self.appointment_a = self._appointment(
            self.patient_a,
            self.doctor_a,
            self.hospital_a,
            self.branch_a,
            1,
        )
        self.appointment_a_other = self._appointment(
            self.patient_a_other,
            self.doctor_a,
            self.hospital_a,
            self.branch_a,
            2,
        )
        self.appointment_a2 = self._appointment(
            self.patient_a2,
            self.doctor_a2,
            self.hospital_a,
            self.branch_a2,
            3,
        )
        self.appointment_b = self._appointment(
            self.patient_b,
            self.doctor_b,
            self.hospital_b,
            self.branch_b,
            4,
        )

        self.order_a = LabOrder.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            appointment=self.appointment_a,
            hospital=self.hospital_a,
            branch=self.branch_a,
            requested_tests_text="CBC Alpha",
            status=LabOrder.Status.PENDING,
        )
        self.order_a2 = LabOrder.objects.create(
            patient=self.patient_a2,
            doctor=self.doctor_a2,
            appointment=self.appointment_a2,
            hospital=self.hospital_a,
            branch=self.branch_a2,
            requested_tests_text="Branch A2 Test",
            status=LabOrder.Status.PENDING,
        )
        self.order_b = LabOrder.objects.create(
            patient=self.patient_b,
            doctor=self.doctor_b,
            appointment=self.appointment_b,
            hospital=self.hospital_b,
            branch=self.branch_b,
            requested_tests_text="Beta Hidden Panel",
            status=LabOrder.Status.PENDING,
        )
        self.unresolved_legacy_appointment = self._appointment(
            self.patient_a,
            self.doctor_a,
            self.hospital_a,
            self.branch_a,
            6,
        )
        Appointment.objects.filter(pk=self.unresolved_legacy_appointment.pk).update(
            hospital=None,
            branch=None,
        )
        self.unresolved_legacy_appointment.refresh_from_db()
        self.unresolved_legacy_order = LabOrder.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            appointment=self.unresolved_legacy_appointment,
            requested_tests_text="Unresolved Legacy Panel",
            status=LabOrder.Status.PENDING,
        )

    def _user(self, email, role):
        user = get_user_model().objects.create_user(
            email=email,
            password=PASSWORD,
            role=role,
            is_approved=True,
        )
        apply_role_permissions(user)
        return user

    def _assign(self, user, role, hospital, branch):
        return StaffAssignment.objects.create(
            user=user,
            role=role,
            hospital=hospital,
            branch=branch,
            is_active=True,
            is_primary=True,
        )

    def _appointment(self, patient, doctor, hospital, branch, hours):
        return Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            hospital=hospital,
            branch=branch,
            scheduled_time=timezone.now() + timedelta(hours=hours),
        )

    def _login(self, user):
        self.client.force_login(user)

    def test_hospital_a_lab_staff_dashboard_excludes_hospital_b_orders(self):
        self._login(self.lab_a)

        response = self.client.get(reverse("lab:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patient Alpha")
        self.assertNotContains(response, "Patient Beta Secret")

    def test_hospital_a_lab_staff_inbox_excludes_hospital_b_orders(self):
        self._login(self.lab_a)

        response = self.client.get(reverse("lab:lab_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patient Alpha")
        self.assertNotContains(response, "Patient Beta Secret")

    def test_hospital_a_search_cannot_discover_hospital_b_order(self):
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:dashboard"),
            {"q": "Beta Hidden"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Patient Beta Secret")
        self.assertEqual(len(response.context["orders_filtered"]), 0)

    def test_hospital_a_dashboard_counts_exclude_hospital_b_orders(self):
        self._login(self.lab_a)

        response = self.client.get(reverse("lab:dashboard"))

        self.assertEqual(response.context["stats"]["pending"], 1)
        self.assertEqual(response.context["stats"]["today_requests"], 1)

    def test_branch_a_lab_staff_cannot_see_branch_a2_orders(self):
        self._login(self.lab_a)

        response = self.client.get(reverse("lab:lab_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patient Alpha")
        self.assertNotContains(response, "Patient Other Branch")

    def test_lab_staff_cannot_get_cross_tenant_order_detail(self):
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_b.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_lab_staff_cannot_post_modify_cross_tenant_order(self):
        self._login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_b.pk}),
            {"result_text": "changed", "action": "save"},
        )

        self.assertEqual(response.status_code, 404)
        self.order_b.refresh_from_db()
        self.assertEqual(self.order_b.status, LabOrder.Status.PENDING)
        self.assertFalse(LabResult.objects.filter(order=self.order_b).exists())

    def test_lab_staff_cannot_update_or_verify_cross_tenant_result(self):
        result = LabResult.objects.create(
            order=self.order_b,
            result_text="original",
        )
        self._login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_b.pk}),
            {"result_text": "changed", "action": "verify"},
        )

        self.assertEqual(response.status_code, 404)
        result.refresh_from_db()
        self.order_b.refresh_from_db()
        self.assertEqual(result.result_text, "original")
        self.assertEqual(result.status, LabResult.Status.DRAFT)
        self.assertIsNone(result.verified_at)
        self.assertEqual(self.order_b.status, LabOrder.Status.PENDING)

    def test_branch_a_lab_staff_cannot_post_modify_branch_a2_order(self):
        self._login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a2.pk}),
            {"result_text": "branch changed", "action": "save"},
        )

        self.assertEqual(response.status_code, 404)
        self.order_a2.refresh_from_db()
        self.assertEqual(self.order_a2.status, LabOrder.Status.PENDING)
        self.assertFalse(LabResult.objects.filter(order=self.order_a2).exists())

    def test_doctor_scoped_to_branch_a_cannot_see_branch_a2_order(self):
        branch_b_assignment = StaffAssignment.objects.create(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
            hospital=self.hospital_b,
            branch=self.branch_b,
            is_active=True,
            is_primary=False,
        )
        appointment_b_for_doctor_a = self._appointment(
            self.patient_a,
            self.doctor_a,
            self.hospital_b,
            self.branch_b,
            5,
        )
        order_b_for_doctor_a = LabOrder.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            appointment=appointment_b_for_doctor_a,
            hospital=self.hospital_b,
            branch=self.branch_b,
            requested_tests_text="Same Doctor Other Branch",
            status=LabOrder.Status.PENDING,
        )
        branch_b_assignment.is_active = False
        branch_b_assignment.save(update_fields=["is_active"])
        self._login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_order_detail",
                kwargs={"order_id": order_b_for_doctor_a.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_doctor_cannot_create_order_for_unauthorized_patient(self):
        self._login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_doctor_cannot_submit_unauthorized_appointment_id(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse("lab:doctor_create_order"),
            {
                "appointment": self.appointment_b.pk,
                "requested_tests_text": "Unauthorized",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            LabOrder.objects.filter(requested_tests_text="Unauthorized").exists()
        )

    def test_patient_appointment_mismatch_is_rejected(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.appointment_a_other.pk,
                "requested_tests_text": "Mismatch",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            LabOrder.objects.filter(requested_tests_text="Mismatch").exists()
        )

    def test_get_lab_order_detail_does_not_change_pending_status(self):
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.order_a.refresh_from_db()
        self.assertEqual(self.order_a.status, LabOrder.Status.PENDING)

    def test_get_doctor_detail_does_not_set_doctor_seen_at(self):
        result = LabResult.objects.create(
            order=self.order_a,
            result_text="ready",
            status=LabResult.Status.VERIFIED,
            verified_by=self.lab_a,
            verified_at=timezone.now(),
        )
        self.order_a.status = LabOrder.Status.READY
        self.order_a.doctor_seen_at = None
        self.order_a.save(update_fields=["status", "doctor_seen_at"])
        self._login(self.doctor_user_a)

        response = self.client.get(
            reverse("lab:doctor_order_detail", kwargs={"order_id": self.order_a.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.order_a.refresh_from_db()
        result.refresh_from_db()
        self.assertIsNone(self.order_a.doctor_seen_at)
        self.assertEqual(result.status, LabResult.Status.VERIFIED)

    def test_authorized_same_tenant_lab_workflow_still_works(self):
        self._login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk}),
            {"result_text": "normal result", "action": "verify"},
        )

        self.assertEqual(response.status_code, 302)
        self.order_a.refresh_from_db()
        result = LabResult.objects.get(order=self.order_a)
        self.assertEqual(self.order_a.status, LabOrder.Status.READY)
        self.assertEqual(result.status, LabResult.Status.VERIFIED)
        self.assertEqual(result.verified_by, self.lab_a)

    def test_authorized_same_tenant_doctor_create_still_works(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.appointment_a.pk,
                "requested_tests_text": "Authorized",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            LabOrder.objects.filter(
                patient=self.patient_a,
                doctor=self.doctor_a,
                appointment=self.appointment_a,
                requested_tests_text="Authorized",
            ).exists()
        )

    def test_appointment_linked_order_snapshots_appointment_tenant(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.appointment_a.pk,
                "requested_tests_text": "Snapshot Appointment",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = LabOrder.objects.get(requested_tests_text="Snapshot Appointment")
        self.assertEqual(order.hospital_id, self.hospital_a.pk)
        self.assertEqual(order.branch_id, self.branch_a.pk)

    def test_appointment_tenant_change_does_not_drift_existing_order(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.appointment_a.pk,
                "requested_tests_text": "Stable Snapshot",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = LabOrder.objects.get(requested_tests_text="Stable Snapshot")

        StaffAssignment.objects.create(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
            hospital=self.hospital_a,
            branch=self.branch_a2,
            is_active=True,
            is_primary=False,
        )
        self.appointment_a.branch = self.branch_a2
        self.appointment_a.save(update_fields=["branch"])

        order.refresh_from_db()
        self.assertEqual(order.hospital_id, self.hospital_a.pk)
        self.assertEqual(order.branch_id, self.branch_a.pk)

    def test_appointmentless_order_with_one_assignment_snapshots_tenant(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": "",
                "requested_tests_text": "Single Assignment",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = LabOrder.objects.get(requested_tests_text="Single Assignment")
        self.assertIsNone(order.appointment_id)
        self.assertEqual(order.hospital_id, self.hospital_a.pk)
        self.assertEqual(order.branch_id, self.branch_a.pk)

    def test_appointmentless_order_with_zero_assignments_is_rejected(self):
        StaffAssignment.objects.filter(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
        ).update(is_active=False)
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": "",
                "requested_tests_text": "No Assignment",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            LabOrder.objects.filter(requested_tests_text="No Assignment").exists()
        )

    def test_appointmentless_order_with_multiple_assignments_requires_context(self):
        StaffAssignment.objects.create(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
            hospital=self.hospital_b,
            branch=self.branch_b,
            is_active=True,
            is_primary=False,
        )
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": "",
                "requested_tests_text": "Ambiguous Assignment",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            LabOrder.objects.filter(requested_tests_text="Ambiguous Assignment").exists()
        )

    def test_appointmentless_order_with_explicit_valid_context_is_allowed(self):
        StaffAssignment.objects.create(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
            hospital=self.hospital_b,
            branch=self.branch_b,
            is_active=True,
            is_primary=False,
        )
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": "",
                "hospital": self.hospital_b.pk,
                "branch": self.branch_b.pk,
                "requested_tests_text": "Explicit Context",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = LabOrder.objects.get(requested_tests_text="Explicit Context")
        self.assertEqual(order.hospital_id, self.hospital_b.pk)
        self.assertEqual(order.branch_id, self.branch_b.pk)

    def test_submitted_tenant_ids_do_not_override_appointment_tenant(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.appointment_a.pk,
                "hospital": self.hospital_b.pk,
                "branch": self.branch_b.pk,
                "requested_tests_text": "Ignored Browser Tenant",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = LabOrder.objects.get(requested_tests_text="Ignored Browser Tenant")
        self.assertEqual(order.hospital_id, self.hospital_a.pk)
        self.assertEqual(order.branch_id, self.branch_a.pk)

    def test_explicit_tenant_blocks_cross_hospital_access(self):
        explicit_order = LabOrder.objects.create(
            patient=self.patient_b,
            doctor=self.doctor_b,
            appointment=self.appointment_b,
            hospital=self.hospital_b,
            branch=self.branch_b,
            requested_tests_text="Explicit Hospital B",
            status=LabOrder.Status.PENDING,
        )
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": explicit_order.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_explicit_tenant_blocks_cross_branch_access(self):
        explicit_order = LabOrder.objects.create(
            patient=self.patient_a2,
            doctor=self.doctor_a2,
            appointment=self.appointment_a2,
            hospital=self.hospital_a,
            branch=self.branch_a2,
            requested_tests_text="Explicit Branch A2",
            status=LabOrder.Status.PENDING,
        )
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": explicit_order.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_unresolved_legacy_order_excluded_from_hospital_a_workflows(self):
        self.assertIsNone(self.unresolved_legacy_order.hospital_id)
        self.assertIsNone(self.unresolved_legacy_order.branch_id)
        self._login(self.lab_a)

        dashboard = self.client.get(reverse("lab:dashboard"))
        inbox = self.client.get(reverse("lab:lab_inbox"))
        search = self.client.get(
            reverse("lab:dashboard"),
            {"q": "Unresolved Legacy"},
        )

        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, "Unresolved Legacy Panel")
        self.assertEqual(dashboard.context["stats"]["pending"], 1)
        self.assertEqual(dashboard.context["stats"]["today_requests"], 1)
        self.assertEqual(inbox.status_code, 200)
        self.assertNotContains(inbox, "Unresolved Legacy Panel")
        self.assertEqual(search.status_code, 200)
        self.assertNotContains(search, "Unresolved Legacy Panel")
        self.assertEqual(len(search.context["orders_filtered"]), 0)

    def test_unresolved_legacy_order_excluded_from_hospital_b_workflows(self):
        self._login(self.lab_b)

        dashboard = self.client.get(reverse("lab:dashboard"))
        inbox = self.client.get(reverse("lab:lab_inbox"))
        search = self.client.get(
            reverse("lab:dashboard"),
            {"q": "Unresolved Legacy"},
        )

        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, "Unresolved Legacy Panel")
        self.assertEqual(dashboard.context["stats"]["pending"], 1)
        self.assertEqual(dashboard.context["stats"]["today_requests"], 1)
        self.assertEqual(inbox.status_code, 200)
        self.assertNotContains(inbox, "Unresolved Legacy Panel")
        self.assertEqual(search.status_code, 200)
        self.assertNotContains(search, "Unresolved Legacy Panel")
        self.assertEqual(len(search.context["orders_filtered"]), 0)

    def test_current_staff_assignment_does_not_expose_unresolved_legacy_order(self):
        appointmentless_order = LabOrder.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            appointment=None,
            requested_tests_text="Appointmentless Legacy Panel",
            status=LabOrder.Status.PENDING,
        )
        StaffAssignment.objects.create(
            user=self.doctor_user_a,
            role=StaffAssignment.Roles.DOCTOR,
            hospital=self.hospital_b,
            branch=self.branch_b,
            is_active=True,
            is_primary=False,
        )

        self._login(self.lab_b)
        lab_response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": appointmentless_order.pk})
        )
        self.assertEqual(lab_response.status_code, 404)

        self._login(self.doctor_user_a)
        doctor_response = self.client.get(
            reverse(
                "lab:doctor_order_detail",
                kwargs={"order_id": appointmentless_order.pk},
            )
        )
        self.assertEqual(doctor_response.status_code, 404)

    def test_appointment_tenant_change_does_not_expose_unresolved_legacy_order(self):
        Appointment.objects.filter(pk=self.unresolved_legacy_appointment.pk).update(
            hospital=self.hospital_a,
            branch=self.branch_a,
        )
        self.unresolved_legacy_order.refresh_from_db()
        self.assertIsNone(self.unresolved_legacy_order.hospital_id)
        self.assertIsNone(self.unresolved_legacy_order.branch_id)
        self._login(self.lab_a)

        detail = self.client.get(
            reverse(
                "lab:lab_order_detail",
                kwargs={"order_id": self.unresolved_legacy_order.pk},
            )
        )
        inbox = self.client.get(reverse("lab:lab_inbox"))

        self.assertEqual(detail.status_code, 404)
        self.assertNotContains(inbox, "Unresolved Legacy Panel")

    def test_unresolved_legacy_lab_direct_detail_is_denied(self):
        self._login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:lab_order_detail",
                kwargs={"order_id": self.unresolved_legacy_order.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_unresolved_legacy_lab_post_write_is_denied(self):
        self._login(self.lab_a)

        response = self.client.post(
            reverse(
                "lab:lab_order_detail",
                kwargs={"order_id": self.unresolved_legacy_order.pk},
            ),
            {"result_text": "changed", "action": "verify"},
        )

        self.assertEqual(response.status_code, 404)
        self.unresolved_legacy_order.refresh_from_db()
        self.assertEqual(self.unresolved_legacy_order.status, LabOrder.Status.PENDING)
        self.assertFalse(
            LabResult.objects.filter(order=self.unresolved_legacy_order).exists()
        )

    def test_unresolved_legacy_doctor_direct_detail_is_denied(self):
        self._login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_order_detail",
                kwargs={"order_id": self.unresolved_legacy_order.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_explicit_snapshot_order_visible_to_correct_branch(self):
        self._login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CBC Alpha")

    def test_creation_with_null_tenant_appointment_is_rejected(self):
        self._login(self.doctor_user_a)

        response = self.client.post(
            reverse(
                "lab:doctor_create_order_patient",
                kwargs={"patient_id": self.patient_a.pk},
            ),
            {
                "appointment": self.unresolved_legacy_appointment.pk,
                "requested_tests_text": "Null Tenant Appointment",
                "urgency": LabOrder.Urgency.NORMAL,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            LabOrder.objects.filter(requested_tests_text="Null Tenant Appointment").exists()
        )
