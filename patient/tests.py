from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.tests.permission_utils import apply_role_permissions
from doctor.models import Doctor
from patient.models import Patient


User = get_user_model()


class PatientSecretaryScopeTests(TestCase):
    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.doctor_a = self._create_doctor(
            email="scope-doctor-a@test.com",
            username="scope_doctor_a",
            full_name="Scope Doctor A",
        )
        self.doctor_b = self._create_doctor(
            email="scope-doctor-b@test.com",
            username="scope_doctor_b",
            full_name="Scope Doctor B",
        )

        self.secretary = User.objects.create_user(
            email="scope-secretary@test.com",
            username="scope_secretary",
            password=self.password,
            role="secretary",
            is_approved=True,
            assigned_doctor=self.doctor_a,
        )
        apply_role_permissions(self.secretary)

        self.patient_a = Patient.objects.create(
            full_name="Visible Scope Patient",
            doctor=self.doctor_a,
        )
        self.patient_b = Patient.objects.create(
            full_name="Foreign Scope Patient",
            doctor=self.doctor_b,
        )

        self.client.force_login(self.secretary)

    def _create_doctor(self, *, email, username, full_name):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=self.password,
            role="doctor",
            is_approved=True,
        )

        return Doctor.objects.create(
            user=user,
            full_name=full_name,
            specialty="General",
        )

    def test_secretary_list_contains_only_assigned_doctor_patients(self):
        response = self.client.get(reverse("patient:list"))

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            patient.pk
            for patient in response.context["patients"].object_list
        }

        self.assertEqual(visible_ids, {self.patient_a.pk})

    def test_secretary_cannot_view_foreign_doctor_patient(self):
        response = self.client.get(
            reverse("patient:detail", args=[self.patient_b.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_secretary_cannot_edit_foreign_doctor_patient(self):
        response = self.client.get(
            reverse("patient:edit", args=[self.patient_b.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_secretary_cannot_spoof_doctor_when_creating_patient(self):
        response = self.client.post(
            reverse("patient:create"),
            {
                "full_name": "Created By Secretary",
                "doctor": self.doctor_b.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        created = Patient.objects.get(
            full_name="Created By Secretary"
        )

        self.assertEqual(created.doctor_id, self.doctor_a.pk)
        self.assertNotEqual(created.doctor_id, self.doctor_b.pk)

    def test_unassigned_secretary_is_denied_patient_list(self):
        unassigned = User.objects.create_user(
            email="unassigned-secretary@test.com",
            username="unassigned_secretary",
            password=self.password,
            role="secretary",
            is_approved=True,
        )
        apply_role_permissions(unassigned)

        self.client.force_login(unassigned)

        response = self.client.get(reverse("patient:list"))

        self.assertEqual(response.status_code, 403)

    def test_secretary_cannot_post_edit_foreign_doctor_patient(self):
        original_name = self.patient_b.full_name

        response = self.client.post(
            reverse("patient:edit", args=[self.patient_b.pk]),
            {
                "full_name": "Tampered Foreign Patient",
            },
        )

        self.assertEqual(response.status_code, 404)

        self.patient_b.refresh_from_db()
        self.assertEqual(self.patient_b.full_name, original_name)

    def test_unassigned_secretary_is_denied_patient_create(self):
        unassigned = User.objects.create_user(
            email="unassigned-create-secretary@test.com",
            username="unassigned_create_secretary",
            password=self.password,
            role="secretary",
            is_approved=True,
        )
        apply_role_permissions(unassigned)

        self.client.force_login(unassigned)

        response = self.client.get(reverse("patient:create"))

        self.assertEqual(response.status_code, 403)