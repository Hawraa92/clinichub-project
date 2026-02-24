# appointments/tests/test_secretary_views.py
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment
from doctor.models import Doctor
from patient.models import Patient

User = get_user_model()


class SecretaryViewsTests(TestCase):
    def setUp(self):
        self.client = Client()

        # سكرتيرة
        self.secretary_user = User.objects.create_user(
            email="sec@example.com",
            password="pass123",
            username="sec",
            role="secretary",
        )

        # دكتور
        doc_user = User.objects.create_user(
            email="doc2@example.com",
            password="pass123",
            username="doc2",
            role="doctor",
        )
        self.doctor = Doctor.objects.create(user=doc_user)

        # مريض
        self.patient = Patient.objects.create(full_name="Sec Patient")

    def login_secretary(self):
        # force_login أكثر ثباتًا بالاختبارات (خصوصًا إذا كانت طريقة تسجيل الدخول مخصصة)
        self.client.force_login(self.secretary_user)

    def future_dt(self, days=0, hour=14):
        """
        يرجّع وقت محلي (local) للمستقبل.
        """
        base = timezone.localtime(timezone.now()) + timedelta(days=days)
        return base.replace(hour=hour, minute=0, second=0, microsecond=0)

    def _local_hour(self, dt):
        """
        يحوّل الوقت إلى localtime إذا كان aware ثم يرجّع الساعة.
        هذا يحل مشكلة فرق التوقيت في الاختبارات.
        """
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        return dt.hour

    def test_secretary_dashboard_requires_role(self):
        # بدون تسجيل = redirect (login_required)
        resp = self.client.get(reverse("appointments:secretary_dashboard"))
        self.assertIn(resp.status_code, (302, 301))

        # دخول بحساب سكرتيرة
        self.login_secretary()
        resp = self.client.get(reverse("appointments:secretary_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("stats", resp.context)

    def test_create_appointment_success(self):
        self.login_secretary()
        url = reverse("appointments:create_appointment")

        data = {
            "doctor": self.doctor.pk,
            "patient": self.patient.pk,
            "scheduled_time": self.future_dt(days=1, hour=16).strftime("%Y-%m-%dT%H:%M"),
            "iqd_amount": 0,
            "status": "pending",  # عدّلي إذا choices مختلفة
        }

        resp = self.client.post(url, data)

        # احتمال فيه redirect للتذكرة أو للقائمة
        self.assertIn(resp.status_code, (302, 303))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_edit_appointment(self):
        self.login_secretary()

        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.future_dt(days=1, hour=9),
        )

        url = reverse("appointments:edit_appointment", args=[appt.pk])
        new_time = self.future_dt(days=1, hour=17)

        data = {
            "doctor": self.doctor.pk,
            "patient": self.patient.pk,
            "scheduled_time": new_time.strftime("%Y-%m-%dT%H:%M"),
            "iqd_amount": 0,
            "status": appt.status,
        }

        resp = self.client.post(url, data)
        self.assertIn(resp.status_code, (302, 303))

        appt.refresh_from_db()

        # ✅ إصلاح فشل الاختبار بسبب timezone (14 بدل 17)
        self.assertEqual(self._local_hour(appt.scheduled_time), 17)

    def test_delete_appointment(self):
        self.login_secretary()

        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.future_dt(days=1, hour=10),
        )

        url = reverse("appointments:delete_appointment", args=[appt.pk])
        resp = self.client.post(url, {})

        self.assertIn(resp.status_code, (302, 303))
        self.assertEqual(Appointment.objects.count(), 0)