# prescription/tests/test_verify_public.py
from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import make_doctor, make_patient, make_appointment, make_prescription


@override_settings(
    SITE_URL="http://testserver",
    PRESCRIPTION_VERIFY_MAX_AGE_DAYS=365,
    PRESCRIPTION_PUBLIC_DOWNLOAD=False,  # default in your code
    PRESCRIPTION_VERIFY_EXPOSE_OBJECT=False,  # default safe
)
class TestPrescriptionPublicVerify(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doctor = make_doctor(email="doc_verify@x.com")
        cls.patient = make_patient(full_name="Sensitive Patient Name", email="pat_verify@x.com")
        cls.appt = make_appointment(cls.doctor, cls.patient)
        cls.rx = make_prescription(cls.appt)

    def test_verify_valid_token_returns_200(self):
        token = self.rx.make_verification_token()
        url = reverse("prescription:verify", kwargs={"token": token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Must not leak patient name in public verify
        self.assertNotIn(self.patient.full_name, resp.content.decode("utf-8", errors="ignore"))

        # If template exposes context: ensure object not exposed by default
        if hasattr(resp, "context") and resp.context is not None:
            self.assertTrue(resp.context.get("is_valid"))
            self.assertIsNone(resp.context.get("prescription"))

    def test_verify_invalid_token_returns_400(self):
        url = reverse("prescription:verify", kwargs={"token": "invalid-token"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 400)

    def test_public_pdf_disabled_by_default(self):
        # public_pdf route exists in your views; should 404 when disabled
        token = self.rx.make_verification_token()
        url = reverse("prescription:public_pdf", kwargs={"token": token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)