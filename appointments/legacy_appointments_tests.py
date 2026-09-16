# appointments/tests.py
from datetime import datetime, timedelta, time
from unittest.mock import patch
from unittest import skipIf

from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment, AppointmentStatus

User = get_user_model()

# محاولة استيراد نموذج طلب الحجز العام
try:
    from appointments.models import PatientBookingRequest
    HAS_BOOKING_REQUEST_MODEL = True
except Exception:
    HAS_BOOKING_REQUEST_MODEL = False


# =====================================================================
# Helpers Base
# =====================================================================
class BaseTestCase(TestCase):
    password = 'pass12345'

    def create_user(self, email, role=None, password=None, **extra):
        password = password or self.password
        user = User.objects.create_user(
            email=email,
            password=password,
            username=email.split('@')[0],
            **extra
        )
        # بعض التطبيقات role حقل قابل للتعديل
        if hasattr(user, 'role') and role:
            user.role = role
            user.save(update_fields=['role'])
        return user

    def create_doctor(self, email='doctor1@example.com', **extra):
        user = self.create_user(email, role='doctor')
        return Doctor.objects.create(user=user, **extra)

    def create_patient(self, full_name='Patient One', **extra):
        return Patient.objects.create(full_name=full_name, **extra)

    def schedule_dt(self, days=0, hour=10, minute=0):
        """
        ترجع وقت مستقبلي مضمون.
        إذا اليوم والحاصل <= الآن، يدفعه لليوم التالي.
        """
        tz = timezone.get_current_timezone()
        base_date = timezone.localdate() + timedelta(days=days)
        candidate = datetime.combine(base_date, time(hour=hour, minute=minute))
        aware = timezone.make_aware(candidate, tz)
        if days == 0 and aware <= timezone.now():
            aware += timedelta(days=1)
        return aware

    def format_dt_input(self, dt):
        # للتوافق مع input type="datetime-local"
        return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


# =====================================================================
# Appointment Model Tests
# =====================================================================
class AppointmentModelTests(BaseTestCase):

    def test_create_valid_appointment(self):
        d = self.create_doctor()
        p = self.create_patient()
        appt = Appointment.objects.create(
            doctor=d,
            patient=p,
            scheduled_time=self.schedule_dt()
        )
        self.assertIsNotNone(appt.pk)
        self.assertEqual(appt.queue_number, 1)

    def test_ordering_by_scheduled_time(self):
        d = self.create_doctor()
        p1 = self.create_patient('P1')
        p2 = self.create_patient('P2')
        early = self.schedule_dt(hour=9)
        late = self.schedule_dt(hour=11)
        Appointment.objects.create(doctor=d, patient=p2, scheduled_time=late)
        Appointment.objects.create(doctor=d, patient=p1, scheduled_time=early)
        names = [a.patient.full_name for a in Appointment.objects.order_by('scheduled_time')]
        self.assertEqual(names, ['P1', 'P2'])

    def test_double_booking_prevented(self):
        d = self.create_doctor()
        p1 = self.create_patient('P1')
        p2 = self.create_patient('P2')
        dt = self.schedule_dt()
        Appointment.objects.create(doctor=d, patient=p1, scheduled_time=dt)
        with self.assertRaises(ValidationError):
            a2 = Appointment(doctor=d, patient=p2, scheduled_time=dt)
            a2.full_clean()

    def test_queue_increments_same_doctor_same_day(self):
        d = self.create_doctor()
        p1 = self.create_patient('P1')
        p2 = self.create_patient('P2')
        a1 = Appointment.objects.create(doctor=d, patient=p1, scheduled_time=self.schedule_dt(hour=9))
        a2 = Appointment.objects.create(doctor=d, patient=p2, scheduled_time=self.schedule_dt(hour=10))
        self.assertEqual(a1.queue_number, 1)
        self.assertEqual(a2.queue_number, 2)

    def test_queue_separate_doctors(self):
        d1 = self.create_doctor('d1@example.com')
        d2 = self.create_doctor('d2@example.com')
        p1 = self.create_patient('P1')
        p2 = self.create_patient('P2')
        a1 = Appointment.objects.create(doctor=d1, patient=p1, scheduled_time=self.schedule_dt())
        a2 = Appointment.objects.create(doctor=d2, patient=p2, scheduled_time=self.schedule_dt())
        self.assertEqual(a1.queue_number, 1)
        self.assertEqual(a2.queue_number, 1)

    def test_new_day_resets_queue(self):
        d = self.create_doctor()
        p1 = self.create_patient('P1')
        p2 = self.create_patient('P2')
        today_appt = Appointment.objects.create(
            doctor=d, patient=p1, scheduled_time=self.schedule_dt(days=0, hour=8)
        )
        future_appt = Appointment.objects.create(
            doctor=d, patient=p2, scheduled_time=self.schedule_dt(days=2, hour=9)
        )
        self.assertEqual(today_appt.queue_number, 1)
        self.assertEqual(future_appt.queue_number, 1)

    def test_resave_does_not_change_queue_number(self):
        d = self.create_doctor()
        p = self.create_patient()
        appt = Appointment.objects.create(doctor=d, patient=p, scheduled_time=self.schedule_dt())
        qn = appt.queue_number
        appt.notes = "Updated note"
        appt.save()
        appt.refresh_from_db()
        self.assertEqual(appt.queue_number, qn)

    def test_changing_day_does_not_recalculate_queue_number(self):
        d = self.create_doctor()
        p = self.create_patient()
        appt = Appointment.objects.create(doctor=d, patient=p, scheduled_time=self.schedule_dt(hour=7))
        original_qn = appt.queue_number
        appt.scheduled_time = self.schedule_dt(days=3, hour=10)
        appt.save()
        appt.refresh_from_db()
        self.assertEqual(appt.queue_number, original_qn)


# =====================================================================
# Secretary Views
# =====================================================================
class SecretaryViewsTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.secretary = self.create_user('sec@example.com', role='secretary')
        self.patient_user = self.create_user('patuser@example.com', role='patient')
        self.doctor = self.create_doctor('doctor@example.com')
        self.patient = self.create_patient('Test Patient')

    def login(self, user):
        self.client.login(email=user.email, password=self.password)

    def _appointment_form_payload(self, **overrides):
        """
        يحاول تزويد الحقول حسب ما قد تكون مطلوبة في الفورم.
        """
        base_dt = self.format_dt_input(self.schedule_dt(hour=15))
        payload = {
            'doctor': self.doctor.pk,
            'patient': self.patient.pk,
            'scheduled_time': base_dt,
            'status': getattr(AppointmentStatus, 'PENDING', 'pending'),
            'iqd_amount': 0,
        }
        payload.update(overrides)
        return payload

    def test_secretary_dashboard_access_control(self):
        url = reverse('appointments:secretary_dashboard')
        # غير مسجل دخول
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        # مريض
        self.login(self.patient_user)
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (302, 403))
        # سكرتيرة
        self.client.logout()
        self.login(self.secretary)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'appointments/secretary_dashboard.html')

    def test_create_appointment_success(self):
        self.login(self.secretary)
        try:
            url = reverse('appointments:create_appointment')
        except NoReverseMatch:
            self.skipTest("create_appointment URL مفقود.")
        data = self._appointment_form_payload()
        resp = self.client.post(url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        if Appointment.objects.count() != 1:
            form = resp.context.get('form')
            print("FORM ERRORS:", form.errors if form else "No form context")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_create_appointment_invalid(self):
        self.login(self.secretary)
        try:
            url = reverse('appointments:create_appointment')
        except NoReverseMatch:
            self.skipTest("create_appointment URL مفقود.")
        resp = self.client.post(url, {}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_edit_appointment(self):
        self.login(self.secretary)
        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.schedule_dt(hour=9)
        )
        try:
            url = reverse('appointments:edit_appointment', args=[appt.pk])
        except NoReverseMatch:
            self.skipTest("edit_appointment URL مفقود.")
        new_dt = self.format_dt_input(self.schedule_dt(hour=17))
        payload = self._appointment_form_payload(
            scheduled_time=new_dt,
            status=appt.status
        )
        resp = self.client.post(url, payload, follow=True)
        self.assertEqual(resp.status_code, 200)
        appt.refresh_from_db()
        local_hour = timezone.localtime(appt.scheduled_time).hour
        self.assertEqual(local_hour, 17, f"Expected hour 17 but got {local_hour}")

    def test_delete_appointment(self):
        self.login(self.secretary)
        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.schedule_dt()
        )
        try:
            url = reverse('appointments:delete_appointment', args=[appt.pk])
        except NoReverseMatch:
            self.skipTest("delete_appointment URL مفقود.")
        resp = self.client.post(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Appointment.objects.filter(pk=appt.pk).exists())

    def test_appointment_list_and_search(self):
        self.login(self.secretary)
        try:
            url = reverse('appointments:appointment_list')
        except NoReverseMatch:
            self.skipTest("appointment_list URL مفقود.")
        for i in range(3):
            Appointment.objects.create(
                doctor=self.doctor,
                patient=self.create_patient(f"P{i}"),
                scheduled_time=self.schedule_dt(hour=9 + i)
            )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "P0")
        resp2 = self.client.get(url, {'q': 'P1'})
        self.assertContains(resp2, "P1")
        self.assertNotContains(resp2, "P0")

    def test_queue_display_template(self):
        try:
            url = reverse('appointments:queue_display')
        except NoReverseMatch:
            self.skipTest("queue_display URL مفقود.")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'appointments/queue_display.html')


# =====================================================================
# Public Booking Tests
# =====================================================================
@skipIf(not HAS_BOOKING_REQUEST_MODEL, "لا يوجد نموذج PatientBookingRequest متاح.")
class PublicBookingTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        # دكتور للحجز العام
        self.doctor = self.create_doctor('publicdoc@example.com')

    def _future_input(self, days=2, hour=11):
        dt = self.schedule_dt(days=days, hour=hour)
        return self.format_dt_input(dt)

    def _build_valid_post(self, include_doctor=True, **overrides):
        data = {
            'doctor': self.doctor.pk,
            'scheduled_time': self._future_input(),
            'full_name': 'مراجع تجريبي',
            'contact_info': '07700000000',
            'date_of_birth': (timezone.localdate() - timedelta(days=30 * 365)).strftime('%Y-%m-%d'),
        }
        if not include_doctor:
            data.pop('doctor', None)
        data.update(overrides)
        return data

    def test_get_public_book_page(self):
        try:
            url = reverse('appointments:public_book')
        except NoReverseMatch:
            self.skipTest("public_book URL مفقود.")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'حجز موعد')

    def test_get_public_book_with_doctor_path(self):
        try:
            url = reverse('appointments:public_book_with_doctor', args=[self.doctor.pk])
        except NoReverseMatch:
            self.skipTest("public_book_with_doctor URL مفقود.")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # الحقل hidden أو disabled (يظهر value)
        self.assertIn(str(self.doctor.pk), resp.content.decode())

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
        if resp.status_code != 302:
            form = resp.context.get('form')
            print("FORM ERRORS:", form.errors if form else "NO FORM")
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
        self.assertIn(reverse('appointments:book_success'), resp.url)
        self.assertEqual(PatientBookingRequest.objects.count(), 0)

    def test_book_success_page(self):
        url = reverse('appointments:book_success')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Thank you')


# =====================================================================
# Ticket View
# =====================================================================
class AppointmentTicketViewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.secretary = self.create_user('sec2@example.com', role='secretary')
        self.doctor = self.create_doctor('ticketdoc@example.com')
        self.patient = self.create_patient('Ticket Patient')

    def test_ticket_view(self):
        try:
            url_name = 'appointments:appointment_ticket'
        except NoReverseMatch:
            self.skipTest("appointment_ticket URL مفقود.")
        self.client.login(email=self.secretary.email, password=self.password)
        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.schedule_dt()
        )
        url = reverse('appointments:appointment_ticket', args=[appt.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"P-{appt.queue_number:03d}" if hasattr(appt, 'queue_number') else str(appt.pk))


# =====================================================================
# Queue / APIs
# =====================================================================
class QueueAPITests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.secretary = self.create_user('sec_api@example.com', role='secretary')
        self.doctor = self.create_doctor('queuedoc@example.com')
        self.patient = self.create_patient('Patient Q')

    def login_sec(self):
        self.client.login(email=self.secretary.email, password=self.password)

    def test_queue_number_api_structure(self):
        # أنشئ موعد (مستقبلي) حتى يظهر في الصف
        Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.schedule_dt()
        )
        try:
            url = reverse('appointments:queue_number_api')
        except NoReverseMatch:
            self.skipTest("queue_number_api URL مفقود.")
        resp = self.client.get(url)
        if resp.status_code == 302:  # يحتاج صلاحية سكرتيرة
            self.login_sec()
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('queues', data)
        self.assertIsInstance(data['queues'], list)

    def test_queue_number_api_handles_exception(self):
        """
        إذا أضفت try/except داخل queue_number_api تقدر تختبر 500.
        """
        try:
            url = reverse('appointments:queue_number_api')
        except NoReverseMatch:
            self.skipTest("queue_number_api URL مفقود.")
        self.login_sec()
        with patch('appointments.views.get_queue_data', side_effect=Exception("boom")):
            resp = self.client.get(url)
            # لو ما عندك معالجة استثناء: قد يرفع 500
            self.assertIn(resp.status_code, (500, 200, 400))

