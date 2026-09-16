from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus
from doctor.models import Doctor
from hospital.models import Branch, Department, Hospital, StaffAssignment
from patient.models import Patient
from pharmacy.models import Pharmacy

from .forms import PrescriptionForm
from .models import Medication, Prescription


User = get_user_model()


class PrescriptionTenantSecurityTests(TestCase):
    password = "SyntheticPrescriptionPass123!"

    def setUp(self):
        self.client = Client()
        self.hospital_a = Hospital.objects.create(
            name="Synthetic Prescription Hospital A",
            code="SYN-RX-HOSP-A",
            is_active=True,
        )
        self.branch_a1 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Synthetic Prescription Branch A1",
            code="SYN-RX-A1",
            is_active=True,
        )
        self.branch_a2 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Synthetic Prescription Branch A2",
            code="SYN-RX-A2",
            is_active=True,
        )
        self.hospital_b = Hospital.objects.create(
            name="Synthetic Prescription Hospital B",
            code="SYN-RX-HOSP-B",
            is_active=True,
        )
        self.branch_b1 = Branch.objects.create(
            hospital=self.hospital_b,
            name="Synthetic Prescription Branch B1",
            code="SYN-RX-B1",
            is_active=True,
        )

        self.doctor_a1, self.assignment_a1 = self._doctor(
            "synthetic-rx-doctor-a1@example.test",
            "Synthetic Doctor A1",
            self.hospital_a,
            self.branch_a1,
        )
        self.doctor_a2, self.assignment_a2 = self._doctor(
            "synthetic-rx-doctor-a2@example.test",
            "Synthetic Doctor A2",
            self.hospital_a,
            self.branch_a2,
        )
        self.doctor_b1, self.assignment_b1 = self._doctor(
            "synthetic-rx-doctor-b1@example.test",
            "Synthetic Doctor B1",
            self.hospital_b,
            self.branch_b1,
        )

        self.patient_a1 = self._patient(
            "synthetic-rx-patient-a1@example.test",
            "Synthetic Patient A1",
        )
        self.patient_a2 = self._patient(
            "synthetic-rx-patient-a2@example.test",
            "Synthetic Patient A2",
        )
        self.patient_b1 = self._patient(
            "synthetic-rx-patient-b1@example.test",
            "Synthetic Patient B1",
        )

        self.appointment_a1 = self._appointment(
            self.doctor_a1,
            self.patient_a1,
            self.hospital_a,
            self.branch_a1,
            1,
        )
        self.appointment_a2 = self._appointment(
            self.doctor_a2,
            self.patient_a2,
            self.hospital_a,
            self.branch_a2,
            2,
        )
        self.appointment_b1 = self._appointment(
            self.doctor_b1,
            self.patient_b1,
            self.hospital_b,
            self.branch_b1,
            3,
        )

        self.prescription_a1 = self._prescription(
            self.appointment_a1,
            self.doctor_a1,
            self.patient_a1,
            "Synthetic Prescription A1",
        )
        self.prescription_a2 = self._prescription(
            self.appointment_a2,
            self.doctor_a2,
            self.patient_a2,
            "Synthetic Prescription A2",
        )
        self.prescription_b1 = self._prescription(
            self.appointment_b1,
            self.doctor_b1,
            self.patient_b1,
            "Synthetic Prescription B1",
        )

        self.secretary_a1 = self._user(
            "synthetic-rx-secretary-a1@example.test",
            "secretary",
        )
        StaffAssignment.objects.create(
            user=self.secretary_a1,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            role=StaffAssignment.Roles.SECRETARY,
            is_primary=True,
            is_active=True,
        )

        self.hospital_admin_a = self._user(
            "synthetic-rx-hospital-admin-a@example.test",
            "admin",
        )
        StaffAssignment.objects.create(
            user=self.hospital_admin_a,
            hospital=self.hospital_a,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        self.branch_admin_a1 = self._user(
            "synthetic-rx-branch-admin-a1@example.test",
            "admin",
        )
        StaffAssignment.objects.create(
            user=self.branch_admin_a1,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        self.superuser = User.objects.create_superuser(
            email="synthetic-rx-superuser@example.test",
            password=self.password,
        )

        self.integrated_pharmacy_a1 = Pharmacy.objects.create(
            branch=self.branch_a1,
            name="Synthetic Integrated Pharmacy A1",
            code="SYN-RX-PH-A1",
            operating_mode=Pharmacy.OperatingModes.INTEGRATED,
            is_active=True,
        )

        self._grant_permissions(
            self.doctor_a1.user,
            "view_prescription",
            "add_prescription",
            "change_prescription",
            "delete_prescription",
        )
        for user in (
            self.patient_a1.user,
            self.secretary_a1,
            self.hospital_admin_a,
            self.branch_admin_a1,
        ):
            self._grant_permissions(
                user,
                "view_prescription",
                "change_prescription",
                "delete_prescription",
                app_label="prescription",
            )
        self._grant_permissions(
            self.doctor_a1.user,
            "add_pharmacyorder",
            app_label="pharmacy",
        )
        self._grant_permissions(
            self.secretary_a1,
            "add_pharmacyorder",
            app_label="pharmacy",
        )
        self._grant_permissions(
            self.hospital_admin_a,
            "add_pharmacyorder",
            app_label="pharmacy",
        )
        self._grant_permissions(
            self.branch_admin_a1,
            "add_pharmacyorder",
            app_label="pharmacy",
        )

    def _user(self, email, role):
        return User.objects.create_user(
            email=email,
            password=self.password,
            role=role,
            is_approved=True,
        )

    def _doctor(self, email, name, hospital, branch):
        user = self._user(email, "doctor")
        doctor = Doctor.objects.create(
            user=user,
            full_name=name,
            specialty="Synthetic Medicine",
        )
        assignment = StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )
        return doctor, assignment

    def _patient(self, email, name):
        user = self._user(email, "patient")
        patient = Patient.objects.get(user=user)
        patient.full_name = name
        patient.email = email
        patient.save(update_fields=["full_name", "email"])
        return patient

    def _appointment(self, doctor, patient, hospital, branch, offset):
        return Appointment.objects.create(
            doctor=doctor,
            patient=patient,
            hospital=hospital,
            branch=branch,
            scheduled_time=timezone.now() + timedelta(days=offset),
            status=AppointmentStatus.PENDING,
        )

    def _prescription(self, appointment, doctor, patient, instruction):
        prescription = Prescription.objects.create(
            appointment=appointment,
            patient=patient,
            doctor=doctor,
            patient_full_name=patient.full_name,
            age=35,
            instructions=instruction,
        )
        Medication.objects.create(
            prescription=prescription,
            name="Synthetic Medicine",
            dosage="1 unit daily",
        )
        return prescription

    @staticmethod
    def _grant_permissions(user, *codenames, app_label="prescription"):
        permissions = Permission.objects.filter(
            content_type__app_label=app_label,
            codename__in=codenames,
        )
        user.user_permissions.add(*permissions)
        for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(name, None)

    @staticmethod
    def _denied(response):
        return response.status_code in (403, 404)

    def test_doctor_can_access_own_prescription(self):
        self.client.force_login(self.doctor_a1.user)
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_a1.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_doctor_cannot_access_foreign_prescription(self):
        self.client.force_login(self.doctor_a1.user)
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_b1.pk])
        )
        self.assertTrue(self._denied(response))

    def test_patient_can_access_own_prescription(self):
        self.client.force_login(self.patient_a1.user)
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_a1.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_patient_cannot_access_foreign_prescription(self):
        self.client.force_login(self.patient_a1.user)
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))

    def test_secretary_and_admins_cannot_access_foreign_detail(self):
        for user in (
            self.secretary_a1,
            self.hospital_admin_a,
            self.branch_admin_a1,
        ):
            self.client.force_login(user)
            response = self.client.get(
                reverse(
                    "prescription:prescription_detail",
                    args=[self.prescription_b1.pk],
                )
            )
            self.assertTrue(self._denied(response), user.email)

    def test_secretary_is_scoped_to_assigned_branch(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(reverse("prescription:list"))
        self.assertEqual(response.status_code, 403)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_is_scoped_to_assigned_branch(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(reverse("prescription:list"))
        self.assertEqual(response.status_code, 200)
        visible = set(response.context["prescriptions"].values_list("pk", flat=True))
        self.assertEqual(visible, {self.prescription_a1.pk})

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_cannot_access_foreign_detail(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))
        response = self.client.get(
            reverse("prescription:prescription_detail", args=[self.prescription_b1.pk])
        )
        self.assertTrue(self._denied(response))

    def test_hospital_admin_is_scoped_to_assigned_hospital(self):
        self.client.force_login(self.hospital_admin_a)
        response = self.client.get(reverse("prescription:list"))
        self.assertEqual(response.status_code, 200)
        visible = set(response.context["prescriptions"].values_list("pk", flat=True))
        self.assertEqual(visible, {self.prescription_a1.pk, self.prescription_a2.pk})

    def test_branch_admin_is_scoped_to_assigned_branch(self):
        self.client.force_login(self.branch_admin_a1)
        response = self.client.get(reverse("prescription:list"))
        self.assertEqual(response.status_code, 200)
        visible = set(response.context["prescriptions"].values_list("pk", flat=True))
        self.assertEqual(visible, {self.prescription_a1.pk})

    def test_superuser_can_list_all_prescriptions(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("prescription:list"))
        self.assertEqual(response.status_code, 200)
        visible = set(response.context["prescriptions"].values_list("pk", flat=True))
        self.assertEqual(
            visible,
            {self.prescription_a1.pk, self.prescription_a2.pk, self.prescription_b1.pk},
        )

    def test_foreign_users_cannot_edit_prescription(self):
        for user in (self.doctor_a1.user, self.secretary_a1, self.hospital_admin_a, self.branch_admin_a1):
            self.client.force_login(user)
            response = self.client.get(
                reverse("prescription:edit", args=[self.prescription_b1.pk])
            )
            self.assertTrue(self._denied(response), user.email)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_cannot_edit_foreign_prescription(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(
            reverse("prescription:edit", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))

    def test_superuser_can_edit_prescription(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("prescription:edit", args=[self.prescription_b1.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_foreign_users_cannot_delete_prescription(self):
        for user in (self.doctor_a1.user, self.secretary_a1, self.hospital_admin_a, self.branch_admin_a1):
            self.client.force_login(user)
            response = self.client.get(
                reverse("prescription:delete", args=[self.prescription_b1.pk])
            )
            self.assertTrue(self._denied(response), user.email)
        self.assertTrue(Prescription.objects.filter(pk=self.prescription_b1.pk).exists())

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_cannot_delete_foreign_prescription(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(
            reverse("prescription:delete", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))

    def test_superuser_can_delete_prescription(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("prescription:delete", args=[self.prescription_b1.pk])
        )
        self.assertRedirects(response, reverse("prescription:list"))
        self.assertFalse(Prescription.objects.filter(pk=self.prescription_b1.pk).exists())

    def test_pdf_download_is_object_scoped(self):
        self.prescription_a1.pdf_file.save(
            "synthetic-a1.pdf",
            ContentFile(b"%PDF-synthetic-a1"),
            save=True,
        )
        self.client.force_login(self.doctor_a1.user)
        own = self.client.get(
            reverse("prescription:download_pdf", args=[self.prescription_a1.pk])
        )
        self.assertEqual(own.status_code, 200)

        foreign = self.client.get(
            reverse("prescription:download_pdf", args=[self.prescription_b1.pk])
        )
        self.assertTrue(self._denied(foreign))

    def test_secretary_and_admins_cannot_download_foreign_pdf(self):
        self.prescription_b1.pdf_file.save(
            "synthetic-b1.pdf",
            ContentFile(b"%PDF-synthetic-b1"),
            save=True,
        )
        for user in (
            self.secretary_a1,
            self.hospital_admin_a,
            self.branch_admin_a1,
        ):
            self.client.force_login(user)
            response = self.client.get(
                reverse(
                    "prescription:download_pdf",
                    args=[self.prescription_b1.pk],
                )
            )
            self.assertTrue(self._denied(response), user.email)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_cannot_download_foreign_pdf(self):
        self.prescription_a2.pdf_file.save(
            "synthetic-a2.pdf",
            ContentFile(b"%PDF-synthetic-a2"),
            save=True,
        )
        self.client.force_login(self.secretary_a1)
        response = self.client.get(
            reverse("prescription:download_pdf", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))

    def test_whatsapp_redirect_is_object_scoped(self):
        self.client.force_login(self.doctor_a1.user)
        own = self.client.get(
            reverse("prescription:send_whatsapp", args=[self.prescription_a1.pk])
        )
        self.assertEqual(own.status_code, 302)
        self.assertIn("wa.me", own["Location"])

        foreign = self.client.get(
            reverse("prescription:send_whatsapp", args=[self.prescription_b1.pk])
        )
        self.assertTrue(self._denied(foreign))

    def test_secretary_and_admins_cannot_share_foreign_prescription(self):
        for user in (
            self.secretary_a1,
            self.hospital_admin_a,
            self.branch_admin_a1,
        ):
            self.client.force_login(user)
            response = self.client.get(
                reverse(
                    "prescription:send_whatsapp",
                    args=[self.prescription_b1.pk],
                )
            )
            self.assertTrue(self._denied(response), user.email)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_cannot_share_foreign_prescription(self):
        self.client.force_login(self.secretary_a1)
        response = self.client.get(
            reverse("prescription:send_whatsapp", args=[self.prescription_a2.pk])
        )
        self.assertTrue(self._denied(response))

    def test_prescription_form_excludes_foreign_appointments_for_doctor(self):
        form = PrescriptionForm(user=self.doctor_a1.user)
        appointment_ids = set(form.fields["appointment"].queryset.values_list("pk", flat=True))
        self.assertEqual(appointment_ids, {self.appointment_a1.pk})

    def test_prescription_form_rejects_foreign_appointment_post(self):
        form = PrescriptionForm(
            data={"appointment": self.appointment_b1.pk},
            user=self.doctor_a1.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("appointment", form.errors)

    def test_secretary_form_is_empty_when_access_disabled(self):
        form = PrescriptionForm(user=self.secretary_a1)
        self.assertFalse(form.fields["appointment"].queryset.exists())

        form = PrescriptionForm(
            data={"appointment": self.appointment_a1.pk},
            user=self.secretary_a1,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("appointment", form.errors)

    def test_admin_forms_exclude_foreign_appointments(self):
        for user, expected_ids in (
            (
                self.hospital_admin_a,
                {self.appointment_a1.pk, self.appointment_a2.pk},
            ),
            (self.branch_admin_a1, {self.appointment_a1.pk}),
        ):
            form = PrescriptionForm(user=user)
            appointment_ids = set(
                form.fields["appointment"].queryset.values_list("pk", flat=True)
            )
            self.assertEqual(appointment_ids, expected_ids, user.email)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_secretary_form_is_scoped_to_assigned_branch(self):
        form = PrescriptionForm(user=self.secretary_a1)
        appointment_ids = set(
            form.fields["appointment"].queryset.values_list("pk", flat=True)
        )
        self.assertEqual(appointment_ids, {self.appointment_a1.pk})

        foreign_form = PrescriptionForm(
            data={"appointment": self.appointment_a2.pk},
            user=self.secretary_a1,
        )
        self.assertFalse(foreign_form.is_valid())
        self.assertIn("appointment", foreign_form.errors)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_hospital_secretary_scope(self):
        secretary = self._user(
            "synthetic-rx-hospital-secretary@example.test",
            "secretary",
        )
        StaffAssignment.objects.create(
            user=secretary,
            hospital=self.hospital_a,
            role=StaffAssignment.Roles.SECRETARY,
            is_primary=True,
            is_active=True,
        )
        form = PrescriptionForm(user=secretary)
        appointment_ids = set(
            form.fields["appointment"].queryset.values_list("pk", flat=True)
        )
        self.assertEqual(
            appointment_ids,
            {self.appointment_a1.pk, self.appointment_a2.pk},
        )

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_enabled_department_secretary_scope(self):
        department = Department.objects.create(
            branch=self.branch_a1,
            name="Synthetic Prescription Department",
            code="SYN-RX-DEPT",
            is_active=True,
        )
        StaffAssignment.objects.create(
            user=self.doctor_a1.user,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            department=department,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=False,
            is_active=True,
        )
        self.appointment_a1.department = department
        self.appointment_a1.save(update_fields=["department"])

        secretary = self._user(
            "synthetic-rx-department-secretary@example.test",
            "secretary",
        )
        StaffAssignment.objects.create(
            user=secretary,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            department=department,
            role=StaffAssignment.Roles.SECRETARY,
            is_primary=True,
            is_active=True,
        )
        form = PrescriptionForm(user=secretary)
        appointment_ids = set(
            form.fields["appointment"].queryset.values_list("pk", flat=True)
        )
        self.assertEqual(appointment_ids, {self.appointment_a1.pk})

    def test_superuser_form_can_select_all_appointments(self):
        form = PrescriptionForm(user=self.superuser)
        appointment_ids = set(
            form.fields["appointment"].queryset.values_list("pk", flat=True)
        )
        self.assertEqual(
            appointment_ids,
            {
                self.appointment_a1.pk,
                self.appointment_a2.pk,
                self.appointment_b1.pk,
            },
        )

    def test_pharmacy_handoff_is_object_scoped(self):
        self.client.force_login(self.doctor_a1.user)
        own = self.client.get(
            reverse("pharmacy:send_prescription", args=[self.prescription_a1.pk])
        )
        self.assertEqual(own.status_code, 200)

        foreign = self.client.get(
            reverse("pharmacy:send_prescription", args=[self.prescription_b1.pk])
        )
        self.assertTrue(self._denied(foreign))

    def test_scoped_admins_cannot_handoff_foreign_prescription(self):
        for user in (self.secretary_a1, self.hospital_admin_a, self.branch_admin_a1):
            self.client.force_login(user)
            response = self.client.get(
                reverse("pharmacy:send_prescription", args=[self.prescription_b1.pk])
            )
            self.assertTrue(self._denied(response), user.email)

    def test_superuser_can_handoff_prescription(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("pharmacy:send_prescription", args=[self.prescription_a1.pk])
        )
        self.assertEqual(response.status_code, 200)
