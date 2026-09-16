from __future__ import annotations

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.tests.permission_utils import apply_role_permissions
from appointments.models import Appointment
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient

from .models import LabOrder, LabResult


PASSWORD = "pass1234"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lab-file-privacy-"))
class LabFilePrivacyTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

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
        self.patient_a2 = Patient.objects.create(
            full_name="Patient Other Branch",
            mobile="+9647701234568",
            doctor=self.doctor_a2,
        )
        self.patient_b = Patient.objects.create(
            full_name="Patient Beta Secret",
            mobile="+9647701234569",
            doctor=self.doctor_b,
        )

        self.appointment_a = self._appointment(
            self.patient_a,
            self.doctor_a,
            self.hospital_a,
            self.branch_a,
        )
        self.appointment_a2 = self._appointment(
            self.patient_a2,
            self.doctor_a2,
            self.hospital_a,
            self.branch_a2,
        )
        self.appointment_b = self._appointment(
            self.patient_b,
            self.doctor_b,
            self.hospital_b,
            self.branch_b,
        )

        self.order_a = self._order(
            self.patient_a,
            self.doctor_a,
            self.appointment_a,
            self.hospital_a,
            self.branch_a,
            "Alpha",
        )
        self.order_a2 = self._order(
            self.patient_a2,
            self.doctor_a2,
            self.appointment_a2,
            self.hospital_a,
            self.branch_a2,
            "Alpha Other Branch",
        )
        self.order_b = self._order(
            self.patient_b,
            self.doctor_b,
            self.appointment_b,
            self.hospital_b,
            self.branch_b,
            "Beta",
        )
        self.unresolved_order = LabOrder.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            requested_tests_text="Unresolved",
            doctor_attachment=self._upload("legacy.pdf", b"%PDF-legacy"),
        )

        self.result_a = LabResult.objects.create(
            order=self.order_a,
            result_text="Alpha result",
            attachment=self._upload("alpha result.pdf", b"%PDF-alpha-result"),
            status=LabResult.Status.VERIFIED,
            verified_by=self.lab_a,
            verified_at=timezone.now(),
        )
        self.result_a2 = LabResult.objects.create(
            order=self.order_a2,
            result_text="Branch A2 result",
            attachment=self._upload("branch-a2-result.pdf", b"%PDF-a2-result"),
        )
        self.result_b = LabResult.objects.create(
            order=self.order_b,
            result_text="Beta result",
            attachment=self._upload("beta-result.pdf", b"%PDF-beta-result"),
        )
        self.unresolved_result = LabResult.objects.create(
            order=self.unresolved_order,
            result_text="Unresolved result",
            attachment=self._upload("legacy-result.pdf", b"%PDF-legacy-result"),
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

    def _appointment(self, patient, doctor, hospital, branch):
        return Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            hospital=hospital,
            branch=branch,
            scheduled_time=timezone.now() + timedelta(hours=1),
        )

    def _upload(self, name, content):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def _order(self, patient, doctor, appointment, hospital, branch, name):
        return LabOrder.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=hospital,
            branch=branch,
            requested_tests_text=name,
            doctor_attachment=self._upload(f"{name} referral.pdf", b"%PDF-order"),
            status=LabOrder.Status.PENDING,
        )

    def _content(self, response):
        return b"".join(response.streaming_content)

    def _assert_private_headers(self, response):
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_unauthenticated_request_is_redirected(self):
        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_hospital_a_lab_staff_can_fetch_own_doctor_attachment(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._content(response), b"%PDF-order")
        self._assert_private_headers(response)
        self.assertIn("inline", response["Content-Disposition"])

    def test_hospital_a_cannot_fetch_hospital_b_doctor_attachment(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_hospital_a_cannot_fetch_hospital_b_result_attachment(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_result_attachment_preview",
                kwargs={"order_id": self.order_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_branch_a_cannot_fetch_branch_a2_files(self):
        self.client.force_login(self.lab_a)

        doctor_file = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_a2.pk},
            )
        )
        result_file = self.client.get(
            reverse(
                "lab:staff_result_attachment_preview",
                kwargs={"order_id": self.order_a2.pk},
            )
        )

        self.assertEqual(doctor_file.status_code, 404)
        self.assertEqual(result_file.status_code, 404)

    def test_unresolved_null_tenant_order_cannot_expose_doctor_attachment(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.unresolved_order.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_unresolved_null_tenant_order_cannot_expose_result_attachment(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_result_attachment_preview",
                kwargs={"order_id": self.unresolved_order.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_authorized_doctor_can_fetch_permitted_result_attachment(self):
        self.client.force_login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_result_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._content(response), b"%PDF-alpha-result")
        self._assert_private_headers(response)

    def test_unauthorized_doctor_cannot_fetch_another_doctor_tenant_file(self):
        self.client.force_login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_result_attachment_preview",
                kwargs={"order_id": self.order_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_authorized_doctor_can_fetch_permitted_doctor_attachment(self):
        self.client.force_login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_order_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._content(response), b"%PDF-order")

    def test_missing_physical_file_returns_404(self):
        storage = self.order_a.doctor_attachment.storage
        storage_name = self.order_a.doctor_attachment.name
        storage.delete(storage_name)
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_post_path_query_cannot_select_arbitrary_filesystem_file(self):
        self.client.force_login(self.lab_a)
        url = reverse(
            "lab:staff_doctor_attachment_preview",
            kwargs={"order_id": self.order_a.pk},
        )

        post_response = self.client.post(url, {"path": "settings.py"})
        query_response = self.client.get(f"{url}?path=settings.py")

        self.assertEqual(post_response.status_code, 405)
        self.assertEqual(query_response.status_code, 200)
        self.assertEqual(self._content(query_response), b"%PDF-order")

    def test_response_content_disposition_uses_safe_basename(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse(
                "lab:staff_doctor_attachment_download",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        disposition = response["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("referral", disposition)
        self.assertNotIn("/", disposition)
        self.assertNotIn("\\", disposition)
        self._assert_private_headers(response)

    def test_lab_detail_template_uses_protected_routes_not_direct_media(self):
        self.client.force_login(self.lab_a)

        response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "lab:staff_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "lab:staff_result_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            ),
        )
        self.assertNotContains(response, "/media/lab/doctor_attachments/")
        self.assertNotContains(response, "/media/lab/results/")

    def test_lab_result_attachment_can_be_replaced_without_public_media_link(self):
        self.client.force_login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk}),
            {
                "result_text": "Updated Alpha result",
                "action": "save",
                "attachment": self._upload("replacement.pdf", b"%PDF-replacement"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.result_a.refresh_from_db()
        self.assertTrue(self.result_a.attachment.name.endswith(".pdf"))
        self.assertIn("replacement", self.result_a.attachment.name)

        detail_response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk})
        )
        self.assertContains(
            detail_response,
            reverse(
                "lab:staff_result_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            ),
        )
        self.assertNotContains(detail_response, "/media/lab/results/")
        self.assertNotContains(detail_response, "/media/lab/doctor_attachments/")

    def test_lab_result_attachment_clear_checkbox_clears_without_public_media_link(self):
        self.client.force_login(self.lab_a)

        response = self.client.post(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk}),
            {
                "result_text": "Result without attachment",
                "action": "save",
                "attachment-clear": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.result_a.refresh_from_db()
        self.assertFalse(self.result_a.attachment)

        detail_response = self.client.get(
            reverse("lab:lab_order_detail", kwargs={"order_id": self.order_a.pk})
        )
        self.assertNotContains(detail_response, "/media/lab/results/")
        self.assertNotContains(detail_response, "/media/lab/doctor_attachments/")

    def test_doctor_detail_template_uses_protected_routes_not_direct_media(self):
        self.client.force_login(self.doctor_user_a)

        response = self.client.get(
            reverse(
                "lab:doctor_order_detail",
                kwargs={"order_id": self.order_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "lab:doctor_order_doctor_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "lab:doctor_result_attachment_preview",
                kwargs={"order_id": self.order_a.pk},
            ),
        )
        self.assertNotContains(response, "/media/lab/doctor_attachments/")
        self.assertNotContains(response, "/media/lab/results/")
