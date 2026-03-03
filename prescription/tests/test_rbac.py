# prescription/tests/test_rbac.py
from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import make_doctor, make_patient, make_appointment, make_prescription, make_user


@override_settings(
    SITE_URL="http://testserver",
    PRESCRIPTION_SECRETARY_CAN_VIEW=False,  # default in your code is False
    PRESCRIPTION_ADMIN_CAN_VIEW=True,       # default True
)
class TestPrescriptionRBAC(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doctor = make_doctor(email="doc_rbac@x.com")
        cls.patient = make_patient(full_name="Hawraa Patient", email="pat_rbac@x.com")
        cls.appt = make_appointment(cls.doctor, cls.patient)
        cls.rx = make_prescription(cls.appt)

        cls.secretary_user = make_user("sec_rbac@x.com", "secretary")
        cls.admin_user = make_user("admin_rbac@x.com", "admin")

    def test_doctor_can_view_detail(self):
        self.client.force_login(self.doctor.user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_patient_can_view_own_detail(self):
        # In your views, patient is allowed to view their own RX via appointment->patient->user
        self.client.force_login(self.patient.user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_secretary_cannot_view_by_default(self):
        self.client.force_login(self.secretary_user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_view_by_default(self):
        self.client.force_login(self.admin_user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    @override_settings(PRESCRIPTION_SECRETARY_CAN_VIEW=True)
    def test_secretary_can_view_when_enabled(self):
        self.client.force_login(self.secretary_user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    @override_settings(PRESCRIPTION_ADMIN_CAN_VIEW=False)
    def test_admin_blocked_when_disabled(self):
        self.client.force_login(self.admin_user)
        url = reverse("prescription:prescription_detail", kwargs={"pk": self.rx.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)