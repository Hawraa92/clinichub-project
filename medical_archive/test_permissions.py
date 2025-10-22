from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive

User = get_user_model()

class ArchiveAccessPermissionTests(TestCase):
    def setUp(self):
        # المريض الأصلي وصاحب الأرشيف
        self.user1 = User.objects.create_user(email='patient1@test.com', password='pass', username='pat1')
        self.patient1 = Patient.objects.create(user=self.user1, full_name='Ali Ahmed')

        # طبيب مرتبط
        self.doctor_user = User.objects.create_user(email='doc@test.com', password='pass', username='doc')
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name='Dr. Test', specialty='Cardiology')

        # مريض آخر (غير مصرح له)
        self.user2 = User.objects.create_user(email='patient2@test.com', password='pass', username='pat2')
        self.patient2 = Patient.objects.create(user=self.user2, full_name='Zainab Other')

        # أرشيف للمريض الأول
        self.archive = PatientArchive.objects.create(
            patient=self.patient1,
            doctor=self.doctor,
            title="سجل خاص",
            archive_type='visit',
            status='final'
        )

    def test_patient_cannot_access_other_patient_archive(self):
        # تسجيل دخول المريض الثاني
        client2 = Client()
        client2.login(email='patient2@test.com', password='pass')
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': self.archive.pk})
        response = client2.get(url)
        # متوقع: 404 أو 403 (حسب فيوك الحالي) لأن الأرشيف مو للمريض
        self.assertIn(response.status_code, [403, 404])

    def test_patient_can_access_own_archive(self):
        # المريض الأصلي (صاحب الأرشيف)
        client1 = Client()
        client1.login(email='patient1@test.com', password='pass')
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': self.archive.pk})
        response = client1.get(url)
        self.assertEqual(response.status_code, 200)

    def test_non_authenticated_user_cannot_access_archive(self):
        # بدون تسجيل دخول
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': self.archive.pk})
        client = Client()
        response = client.get(url)
        # متوقع: redirect (302) للصفحة تسجيل الدخول
        self.assertIn(response.status_code, [302, 403, 404])

    def test_doctor_can_access_patient_archive(self):
        # الطبيب المشرف
        client_doc = Client()
        client_doc.login(email='doc@test.com', password='pass')
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': self.archive.pk})
        response = client_doc.get(url)
        self.assertEqual(response.status_code, 200)

    def test_random_user_cannot_access_any_archive(self):
        random_user = User.objects.create_user(email='random@test.com', password='pass', username='rnd')
        client_rnd = Client()
        client_rnd.login(email='random@test.com', password='pass')
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': self.archive.pk})
        response = client_rnd.get(url)
        self.assertIn(response.status_code, [403, 404])
