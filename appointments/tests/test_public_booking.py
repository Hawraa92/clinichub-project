from datetime import timedelta
from django.utils import timezone
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from doctor.models import Doctor
from appointments.models import PatientBookingRequest  # عدّلي إذا مختلف

User = get_user_model()


class PublicBookingTests(TestCase):
    def setUp(self):
        self.client = Client()
        user = User.objects.create_user(
            email='publicdoc@example.com',
            password='pass123',
            username='publicdoc',
            role='doctor'
        )
        self.doctor = Doctor.objects.create(user=user)

    def _future_dt(self, days=2, hour=11, minute=0):
        dt = timezone.localtime(timezone.now()) + timedelta(days=days)
        dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.strftime('%Y-%m-%dT%H:%M')

    def _build_valid_post(self, include_doctor=True, **overrides):
        data = {
            'doctor': self.doctor.pk,
            'scheduled_time': self._future_dt(),
            'full_name': 'مراجع تجريبي',
            'contact_info': '07700000000',
            'date_of_birth': (timezone.localdate() - timedelta(days=30*365)).strftime('%Y-%m-%d'),
        }
        if not include_doctor:
            data.pop('doctor', None)
        data.update(overrides)
        return data

    def test_get_public_book_page(self):
        url = reverse('appointments:public_book')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'حجز موعد')

    def test_get_public_book_with_doctor_path(self):
        url = reverse('appointments:public_book_with_doctor', args=[self.doctor.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'name="doctor" value="{self.doctor.pk}"', resp.content.decode())

    def test_post_valid_booking(self):
        url = reverse('appointments:public_book')
        data = self._build_valid_post()
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('appointments:book_success'), resp.url)
        self.assertTrue(PatientBookingRequest.objects.exists())

    def test_post_valid_booking_with_path_doctor(self):
        url = reverse('appointments:public_book_with_doctor', args=[self.doctor.pk])
        data = self._build_valid_post(include_doctor=False)
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        req = PatientBookingRequest.objects.latest('id')
        self.assertEqual(req.doctor_id, self.doctor.pk)

    def test_post_invalid_missing_fields(self):
        url = reverse('appointments:public_book')
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PatientBookingRequest.objects.count(), 0)

    def test_honeypot_blocks_bot(self):
        url = reverse('appointments:public_book')
        data = self._build_valid_post()
        data['hp_field'] = 'bot'
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PatientBookingRequest.objects.count(), 0)

    def test_book_success_page(self):
        url = reverse('appointments:book_success')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Thank you')
