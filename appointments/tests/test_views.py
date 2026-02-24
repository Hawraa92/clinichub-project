# appointments/tests/test_views.py
from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.encoding import force_str

from appointments.models import Appointment, AppointmentStatus, PatientBookingRequest
from .factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientBookingRequestFactory,  # keep for compatibility / future tests
    PatientFactory,
    UserFactory,
)


def _to_form_datetime(dt) -> str:
    """
    صيغة مناسبة غالبًا لحقل <input type="datetime-local">
    (وهذا هو سبب شائع لفشل test_post_create_valid_appointment)
    """
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.strftime("%Y-%m-%dT%H:%M")


class BaseViewTestCase(TestCase):
    """
    يُستخدم كوراثة مشتركة لتجهيز عميل (Client) ومستخدم سكرتير وتسجيل دخوله.
    """

    def setUp(self):
        self.client = Client()
        # نضمن أن هذا المستخدم role=secretary
        self.secretary = UserFactory(role="secretary", username="sec_user")
        self.client.force_login(self.secretary)


class PermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.not_secretary = UserFactory(role="other", username="other_user")
        self.client.force_login(self.not_secretary)

    def test_secretary_dashboard_forbidden_if_not_secretary(self):
        url = reverse("appointments:secretary_dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)  # HttpResponseForbidden

    def test_secretary_dashboard_requires_login(self):
        self.client.logout()
        url = reverse("appointments:secretary_dashboard")
        resp = self.client.get(url)
        # إعادة التوجيه لصفحة تسجيل الدخول (اعتماداً على إعداداتك LOGIN_URL)
        self.assertIn(resp.status_code, (302, 301))
        self.assertIn("login", resp.url.lower())


class SecretaryDashboardTests(BaseViewTestCase):
    def test_dashboard_renders(self):
        url = reverse("appointments:secretary_dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Weekly Patients Overview")

    def test_dashboard_stats_counts(self):
        d = DoctorFactory()
        p = PatientFactory()
        AppointmentFactory(
            doctor=d,
            patient=p,
            scheduled_time=timezone.now() + timedelta(minutes=10),
        )
        url = reverse("appointments:secretary_dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("stats", resp.context)
        self.assertIsInstance(resp.context["stats"]["appointments_today"], int)


class CreateAppointmentViewTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()
        self.url = reverse("appointments:create_appointment")

    def test_get_create_appointment_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<form")

    def test_post_create_valid_appointment(self):
        # ✅ استخدم datetime-local بدل "YYYY-MM-DD HH:MM:SS" لأن أغلب الفورمز تتوقع هذه الصيغة
        scheduled = _to_form_datetime(timezone.now() + timedelta(hours=1))

        data = {
            "patient": self.patient.id,
            "doctor": self.doctor.id,
            "scheduled_time": scheduled,
            "status": AppointmentStatus.PENDING,
            "iqd_amount": 10000,
        }

        # لا نستخدم follow=True حتى لا يختفي سبب الفشل (redirect vs form error)
        resp = self.client.post(self.url, data)

        # إذا كان الحفظ ناجحًا، المفروض redirect
        self.assertIn(
            resp.status_code,
            (302, 303),
            msg=f"Expected redirect on valid POST, got {resp.status_code}. "
                f"Body: {force_str(resp.content, errors='ignore')[:800]}",
        )

        self.assertTrue(
            Appointment.objects.filter(doctor=self.doctor, patient=self.patient).exists(),
            msg="Appointment was not created. غالبًا الفورم رفض scheduled_time أو حقل آخر.",
        )

    def test_post_create_invalid_missing_required(self):
        resp = self.client.post(self.url, {})  # متعمد نترك الحقول
        self.assertEqual(resp.status_code, 200)

        body = force_str(resp.content, errors="ignore")
        # ✅ الاختبار يعتمد على مؤشرات UI ثابتة بدل كلمة error حرفياً
        self.assertTrue(
            ("alert-danger" in body)
            or ("لم يتم حفظ الموعد" in body)
            or ("Please correct" in body)
            or ("errorlist" in body)
        )


class AppointmentListViewTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.p1 = PatientFactory(full_name="Alpha Patient")
        self.p2 = PatientFactory(full_name="Beta Patient")

        AppointmentFactory(
            doctor=self.doctor,
            patient=self.p1,
            scheduled_time=timezone.now() + timedelta(minutes=10),
            queue_number=1,
        )
        AppointmentFactory(
            doctor=self.doctor,
            patient=self.p2,
            scheduled_time=timezone.now() + timedelta(minutes=20),
            queue_number=2,
        )
        self.url = reverse("appointments:appointment_list")

    def test_list_default(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Patient")
        self.assertContains(resp, "Beta Patient")

    def test_search_patient_name(self):
        resp = self.client.get(self.url, {"q": "Alpha"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Patient")
        self.assertNotContains(resp, "Beta Patient")

    def test_sort_by_patient(self):
        resp = self.client.get(self.url, {"sort": "patient"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Patient")
        self.assertContains(resp, "Beta Patient")


class BookingPublicViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.doctor = DoctorFactory()
        self.url = reverse("appointments:book_appointment_public")

    def _doctor_locked_url(self) -> str:
        """
        بعض المشاريع عندها path بالدكتور (…/book/<id>/)
        وبعضها تعتمد query param (?doctor_id=)
        نخلي الاختبار يدعم الاثنين بشكل نظيف.
        """
        try:
            return reverse("appointments:book_appointment_public", args=[self.doctor.id])
        except NoReverseMatch:
            return self.url  # نستخدم query param لاحقاً

    def test_get_form_basic(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<form")

    def test_get_with_doctor_id_prefills_and_disables(self):
        locked_url = self._doctor_locked_url()

        if locked_url == self.url:
            resp = self.client.get(self.url, {"doctor_id": self.doctor.id})
        else:
            resp = self.client.get(locked_url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "disabled")

        # ✅ نتأكد hidden doctor موجود
        self.assertIn(
            f'name="doctor" value="{self.doctor.id}"'.encode(),
            resp.content,
        )

    def test_post_honeypot_trap(self):
        data = {
            "full_name": "Spam Bot",
            "contact_info": "123",
            "scheduled_time": _to_form_datetime(timezone.now() + timedelta(days=1)),
            "hp_field": "I AM A BOT",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PatientBookingRequest.objects.filter(full_name="Spam Bot").exists())

    def test_post_valid_booking(self):
        data = {
            "full_name": "Real User",
            "contact_info": "0770000000",
            "scheduled_time": _to_form_datetime(timezone.now() + timedelta(days=1)),
            "doctor": self.doctor.id,
        }
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(PatientBookingRequest.objects.filter(full_name="Real User").exists())


class APIsTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()

        self.appt1 = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=5),
            queue_number=1,
            status=AppointmentStatus.PENDING,
        )
        self.appt2 = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=15),
            queue_number=2,
            status=AppointmentStatus.PENDING,
        )
        self.appt3 = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=25),
            queue_number=3,
            status=AppointmentStatus.PENDING,
        )

    def test_new_booking_requests_api_empty(self):
        url = reverse("appointments:new_booking_requests_api")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("booking_requests", data)
        self.assertEqual(data["count"], 0)

    def test_queue_number_api_structure(self):
        url = reverse("appointments:queue_number_api")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("queues", data)
        self.assertTrue(len(data["queues"]) >= 1)

    def test_current_patient_api(self):
        url = reverse("appointments:current_patient_api")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("current_patient", data)

    def test_call_next_api_marks_completed(self):
        url = reverse("appointments:call_next_api", args=[self.doctor.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

        self.appt1.refresh_from_db()
        self.assertEqual(self.appt1.status, AppointmentStatus.COMPLETED)

    def test_call_next_api_until_empty(self):
        url = reverse("appointments:call_next_api", args=[self.doctor.id])
        self.client.post(url)
        self.client.post(url)
        self.client.post(url)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


class SettingsViewTests(BaseViewTestCase):
    def test_settings_get(self):
        url = reverse("appointments:secretary_settings")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Settings")

    def test_settings_post(self):
        url = reverse("appointments:secretary_settings")
        resp = self.client.post(
            url,
            {"full_name": "New Name", "email": "newmail@example.com"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)

        # ✅ لا نعتمد على messages storage بعد follow لأن الرسائل قد تُستهلك داخل القالب أثناء الرندر
        body = force_str(resp.content, errors="ignore")
        self.assertTrue(
            ("Settings saved" in body)
            or ("saved successfully" in body.lower())
            or ("تم حفظ" in body)
            or ("alert-success" in body)
            or ("toast success" in body)
            or ("✅" in body)
        )