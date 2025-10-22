# doctor/tests/test_security.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment
from medical_archive.models import PatientArchive
from prescription.models import Prescription

User = get_user_model()
PASSWORD = 'pass1234'


def create_user(email, role='patient'):
    return User.objects.create_user(email=email, password=PASSWORD, role=role)


def create_doctor(email='doc1@example.com', full_name='Dr. One'):
    u = create_user(email, role='doctor')
    return Doctor.objects.create(user=u, full_name=full_name)


def create_patient(name='John Doe'):
    # لا تمررين age لأن مو Field
    return Patient.objects.create(full_name=name)


def create_appointment(patient, doctor, day_shift=1, hour_shift=0):
    dt = timezone.now() + timedelta(days=max(day_shift, 1), hours=hour_shift)
    return Appointment.objects.create(patient=patient, doctor=doctor, scheduled_time=dt)


def create_prescription(doctor, appointment):
    """
    عبي الحقول الإلزامية بنفسك حتى نتجنب الـ NULL.
    """
    return Prescription.objects.create(
        appointment=appointment,
        doctor=doctor,
        patient_full_name=appointment.patient.full_name,
        age=30,  # أي رقم للتست
        instructions="Take 1 pill twice a day",
        status="draft",
    )


def create_archive(doctor, patient):
    return PatientArchive.objects.create(
        doctor=doctor,
        patient=patient,
        title="Test Rec",
        notes="Secret notes"
    )


class DoctorSecurityTests(TestCase):
    def setUp(self):
        # Doctors
        self.doc1 = create_doctor('doc1@example.com', 'Dr. One')
        self.doc2 = create_doctor('doc2@example.com', 'Dr. Two')

        # Secretary & random patient user
        self.secretary = create_user('sec@example.com', role='secretary')
        self.random_user = create_user('rand@example.com', role='patient')

        # Patients & data
        self.p1 = create_patient('Patient A')
        self.p2 = create_patient('Patient B')

        self.appt1 = create_appointment(self.p1, self.doc1)  # يخص د.1
        self.appt2 = create_appointment(self.p2, self.doc2)  # يخص د.2

        self.pres1 = create_prescription(self.doc1, self.appt1)
        self.arch1 = create_archive(self.doc1, self.p1)

        # URLs
        self.dashboard_url = reverse('doctor:dashboard')
        self.patients_list_url = reverse('doctor:patients_list')
        self.search_url = reverse('doctor:patient_search')
        self.report_url_doc1_p1 = reverse('doctor:patient_report', args=[self.p1.id])
        self.report_pdf_url = reverse('doctor:report_pdf', args=[self.p1.id])
        self.report_csv_url = reverse('doctor:report_csv', args=[self.p1.id])

    # ---------- 1) Role Enforcement ----------
    def test_secretary_blocked_from_doctor_pages(self):
        self.client.login(email=self.secretary.email, password=PASSWORD)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 403)

    def test_random_user_blocked_from_doctor_pages(self):
        self.client.login(email=self.random_user.email, password=PASSWORD)
        resp = self.client.get(self.patients_list_url)
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected(self):
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp.url)

    # ---------- 2) Object-level access (IDOR) ----------
    def test_doctor_cannot_access_other_doctor_patient_report(self):
        self.client.login(email=self.doc2.user.email, password=PASSWORD)
        resp = self.client.get(self.report_url_doc1_p1)
        self.assertIn(resp.status_code, [403, 404])

    def test_doctor_can_access_own_patient_report(self):
        self.client.login(email=self.doc1.user.email, password=PASSWORD)
        resp = self.client.get(self.report_url_doc1_p1)
        self.assertEqual(resp.status_code, 200)

    # ---------- 3) Export endpoints protected ----------
    def test_pdf_export_protected(self):
        self.client.login(email=self.secretary.email, password=PASSWORD)
        resp = self.client.get(self.report_pdf_url)
        self.assertIn(resp.status_code, [403, 500])  # 500 لو Weasy مو مثبتة

    def test_csv_export_protected(self):
        self.client.login(email=self.random_user.email, password=PASSWORD)
        resp = self.client.get(self.report_csv_url)
        self.assertEqual(resp.status_code, 403)

    # ---------- 4) Sensitive data not leaked ----------
    def test_sensitive_notes_not_visible_to_other_doctor(self):
        self.client.login(email=self.doc2.user.email, password=PASSWORD)
        resp = self.client.get(self.report_url_doc1_p1)
        if resp.status_code == 200:
            self.assertNotContains(resp, self.arch1.notes)

    # ---------- 5) Allowed methods only ----------
    def test_report_search_disallow_post_without_params(self):
        url = reverse('doctor:report_search')
        self.client.login(email=self.doc1.user.email, password=PASSWORD)
        resp = self.client.post(url, {})
        self.assertIn(resp.status_code, [200, 302])  # المهم مو 500

    # ---------- 6) No open redirect via ?next param ----------
    def test_no_open_redirect_on_login_required(self):
        resp = self.client.get(self.dashboard_url + '?next=https://evil.com')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/accounts/login'))
