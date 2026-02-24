# appointments/tests/test_queue_api.py
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus
from doctor.models import Doctor
from patient.models import Patient

User = get_user_model()


class QueueAPITests(TestCase):
    def setUp(self):
        self.client = Client()

        # سكرتيرة
        self.sec_user = User.objects.create_user(
            email="secq@example.com",
            password="pass123",
            username="secq",
            role="secretary",
        )

        # دكتور + مريض
        doc_user = User.objects.create_user(
            email="qdoc@example.com",
            password="pass123",
            username="qdoc",
            role="doctor",
        )
        self.doctor = Doctor.objects.create(user=doc_user)
        self.patient = Patient.objects.create(full_name="Queue Patient")

    def login_sec(self) -> None:
        # يعتمد على أن نظام تسجيل الدخول عندك يدعم email
        self.client.login(email="secq@example.com", password="pass123")

    def future_today_dt(self, minutes_ahead: int = 10):
        """
        يرجّع وقت مستقبلي + يضمن يبقى بنفس اليوم المحلي (حتى يطابق فلترة API لليوم الحالي).
        """
        now_local = timezone.localtime(timezone.now())

        candidate = now_local + timedelta(minutes=minutes_ahead)

        # إذا قربنا من منتصف الليل وصار التاريخ يتغير، نخليه نهاية اليوم (ويبقى Future)
        if candidate.date() != now_local.date():
            candidate = now_local.replace(hour=23, minute=59, second=59, microsecond=0)

        return candidate

    def test_queue_number_api_empty(self):
        self.login_sec()
        url = reverse("appointments:queue_number_api")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("queues", resp.json())

    def test_queue_number_api_with_appointment(self):
        self.login_sec()

        Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.future_today_dt(),
            status=AppointmentStatus.PENDING,
        )

        url = reverse("appointments:queue_number_api")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["queues"])