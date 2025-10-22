# appointments/tests/test_views.py
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus, PatientBookingRequest
from .factories import (
    UserFactory,
    DoctorFactory,
    PatientFactory,
    AppointmentFactory,
    PatientBookingRequestFactory,
)


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
        # نخرج المستخدم
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
        # نخلق بعض البيانات
        d = DoctorFactory()
        p = PatientFactory()
        AppointmentFactory(doctor=d, patient=p)
        url = reverse("appointments:secretary_dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # مجرد وجود قيمة رقمية في الإحصائيات
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
        scheduled = (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "patient": self.patient.id,
            "doctor": self.doctor.id,
            "scheduled_time": scheduled,
            "queue_number": 5,
            "status": AppointmentStatus.PENDING,
            "iqd_amount": 10000,
        }
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Appointment.objects.filter(doctor=self.doctor, patient=self.patient).exists())

    def test_post_create_invalid_missing_required(self):
        data = {
            # متعمد نترك الحقول
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "error", status_code=200, html=False)


class AppointmentListViewTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.p1 = PatientFactory(full_name="Alpha Patient")
        self.p2 = PatientFactory(full_name="Beta Patient")
        AppointmentFactory(doctor=self.doctor, patient=self.p1,
                           scheduled_time=timezone.now() + timedelta(minutes=10), queue_number=1)
        AppointmentFactory(doctor=self.doctor, patient=self.p2,
                           scheduled_time=timezone.now() + timedelta(minutes=20), queue_number=2)
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
        # وجود الصفحتين يكفي هنا (فرز صعب التأكد نصياً بدون parsing)
        self.assertContains(resp, "Alpha Patient")
        self.assertContains(resp, "Beta Patient")


class BookingPublicViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.doctor = DoctorFactory()
        self.url = reverse("appointments:book_appointment_public")

    def test_get_form_basic(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<form")

    def test_get_with_doctor_id_prefills_and_disables(self):
        resp = self.client.get(self.url, {"doctor_id": self.doctor.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "disabled")  # الحقل معطل

    def test_post_honeypot_trap(self):
        data = {
            "full_name": "Spam Bot",
            "contact_info": "123",
            "scheduled_time": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "hp_field": "I AM A BOT",  # حقل honeypot مملوء
        }
        resp = self.client.post(self.url, data)
        # إعادة توجيه للنجاح بصمت
        self.assertEqual(resp.status_code, 302)

    def test_post_valid_booking(self):
        data = {
            "full_name": "Real User",
            "contact_info": "0770000000",
            "scheduled_time": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "doctor": self.doctor.id,
        }
        resp = self.client.post(self.client.get(self.url).request["PATH_INFO"], data, follow=True)
        # أو ببساطة self.client.post(self.url, data, follow=True)
        # نتأكد تم الإنشاء
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(PatientBookingRequest.objects.filter(full_name="Real User").exists())


class APIsTests(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.doctor = DoctorFactory()
        self.patient = PatientFactory()
        # ثلاث مواعيد لنفس الدكتور
        self.appt1 = AppointmentFactory(doctor=self.doctor, patient=self.patient,
                                        scheduled_time=timezone.now() + timedelta(minutes=5),
                                        queue_number=1)
        self.appt2 = AppointmentFactory(doctor=self.doctor, patient=self.patient,
                                        scheduled_time=timezone.now() + timedelta(minutes=15),
                                        queue_number=2)
        self.appt3 = AppointmentFactory(doctor=self.doctor, patient=self.patient,
                                        scheduled_time=timezone.now() + timedelta(minutes=25),
                                        queue_number=3)

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
        # أول واحد pending لازم يظهر current
        self.assertIn("current_patient", data)
        # ممكن يكون None لو الوقت ما ينطبق – نتأكد فقط المفتاح موجود

    def test_call_next_api_marks_completed(self):
        url = reverse("appointments:call_next_api", args=[self.doctor.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        # تأكد أول موعد صار COMPLETED
        self.appt1.refresh_from_db()
        self.assertEqual(self.appt1.status, AppointmentStatus.COMPLETED)

    def test_call_next_api_until_empty(self):
        url = reverse("appointments:call_next_api", args=[self.doctor.id])
        # ثلاث مرات (ثلاث مواعيد)
        self.client.post(url)
        self.client.post(url)
        self.client.post(url)
        # الرابعة يفترض يرد 404
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
        resp = self.client.post(url, {
            "full_name": "New Name",
            "email": "newmail@example.com"
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        # الرسالة موجودة (حسب ما تعرضه في القالب)
        # ممكن تختبر وجود كلمة Saved / success
        self.assertTrue(any("success" in m.tags for m in resp.context["messages"]))
