# accounts/tests/test_accounts_extended.py
"""
Extended test suite for the ClinicHub `accounts` app.

يغطي:
- موديل المستخدم (تطبيع البريد، موافقة حسب الدور، السوبر).
- PatientSignUpForm (عدم تطابق كلمة مرور، بريد مكرر، username تلقائي).
- ApprovedAuthenticationForm (منع غير الموافقين).
- التسجيل + تسجيل الدخول + إعادة التوجيه حسب الدور + دعم ?next= + حماية redirect خارجي.
- staff-login (اختياري).
- تدفق إعادة ضبط كلمة المرور (إرسال بريد + تأكيد + تغيير + تسجيل الدخول).

عدّلي أسماء المسارات إذا مختلفة في مشروعك.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse, NoReverseMatch
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.contrib.auth.tokens import default_token_generator

from accounts.forms import PatientSignUpForm, ApprovedAuthenticationForm
from patient.models import Patient

User = get_user_model()


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def safe_reverse(name: str, default: str = "/") -> str:
    """Try reverse(); if missing, return default."""
    try:
        return reverse(name)
    except NoReverseMatch:
        return default


def strong_pass() -> str:
    """Password likely to satisfy validators."""
    return "StrongPass123!"


def _rel_from_location(location: str) -> str:
    """
    Extract relative path+query from a Location header that may be absolute.
    """
    parts = urlsplit(location)
    rel = parts.path
    if parts.query:
        rel += f"?{parts.query}"
    return rel or "/"


class AccountsBaseCase(TestCase):
    """Shared URL lookups used across all extended tests."""
    @classmethod
    def setUpTestData(cls):
        cls.url_register = reverse("accounts:register")
        cls.url_login = reverse("accounts:login")
        cls.url_logout = reverse("accounts:logout")
        cls.url_home = safe_reverse("home:index", "/")
        cls.url_patient_dashboard = safe_reverse("patient:dashboard", "/")
        cls.url_doctor_dashboard = safe_reverse("doctor:dashboard", "/")
        cls.url_secretary_dashboard = safe_reverse("appointments:secretary_dashboard", "/")
        cls.url_admin_index = reverse("admin:index")


# ------------------------------------------------------------------
# model tests
# ------------------------------------------------------------------
class ExtendedUserModelTest(AccountsBaseCase):
    def test_email_normalized_lowercase(self):
        u = User.objects.create_user(email="MiXeD@Example.COM", password="x")
        self.assertEqual(u.email, "mixed@example.com")

    def test_patient_auto_approved(self):
        u = User.objects.create_user(email="p_auto@example.com", password="x")
        self.assertTrue(u.is_approved)
        self.assertEqual(u.role, "patient")

    def test_doctor_requires_approval(self):
        u = User.objects.create_user(email="d_auto@example.com", password="x", role="doctor")
        self.assertFalse(u.is_approved)

    def test_superuser_forces_admin_role_and_flags(self):
        su = User.objects.create_superuser(email="root@example.com", password="rootpass")
        self.assertTrue(su.is_superuser)
        self.assertTrue(su.is_staff)
        self.assertTrue(su.is_approved)
        self.assertEqual(su.role, "admin")


# ------------------------------------------------------------------
# PatientSignUpForm tests
# ------------------------------------------------------------------
class ExtendedPatientSignUpFormTest(AccountsBaseCase):
    def setUp(self):
        self.valid = {
            "email": "formpatient@example.com",
            "username": "formpatient",
            "password1": strong_pass(),
            "password2": strong_pass(),
        }

    def test_password_mismatch(self):
        data = dict(self.valid)
        data["password2"] = "OtherPass999!"
        form = PatientSignUpForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)  # mismatch error attaches here

    def test_duplicate_email_case_insensitive(self):
        User.objects.create_user(email="dup@Example.com", password="x")
        data = dict(self.valid)
        data["email"] = "Dup@example.COM"
        form = PatientSignUpForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_username_optional_autofill(self):
        data = dict(self.valid)
        data["username"] = ""  # leave blank → auto from email
        form = PatientSignUpForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, "formpatient")


# ------------------------------------------------------------------
# ApprovedAuthenticationForm tests
# ------------------------------------------------------------------
class ExtendedApprovedAuthenticationFormTest(AccountsBaseCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.email = "authuser@example.com"
        self.password = strong_pass()
        self.user = User.objects.create_user(email=self.email, password=self.password)

    def test_denies_unapproved_user(self):
        self.user.is_approved = False
        self.user.save()
        req = self.rf.post(self.url_login)
        form = ApprovedAuthenticationForm(req, data={"username": self.email, "password": self.password})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_allows_approved_user(self):
        self.user.is_approved = True
        self.user.save()
        req = self.rf.post(self.url_login)
        form = ApprovedAuthenticationForm(req, data={"username": self.email, "password": self.password})
        self.assertTrue(form.is_valid(), form.errors)


# ------------------------------------------------------------------
# register view tests
# ------------------------------------------------------------------
class ExtendedRegisterViewTest(AccountsBaseCase):
    def setUp(self):
        self.client = Client()
        self.payload = {
            "email": "viewpatient@example.com",
            "username": "viewpatient",
            "password1": strong_pass(),
            "password2": strong_pass(),
        }

    def test_register_creates_user_and_patient(self):
        resp = self.client.post(self.url_register, self.payload)
        self.assertRedirects(resp, self.url_login)
        user = User.objects.get(email="viewpatient@example.com")
        self.assertTrue(Patient.objects.filter(user=user).exists())

    def test_register_duplicate_email_stays(self):
        User.objects.create_user(email="dup3@example.com", password="x")
        data = dict(self.payload)
        data["email"] = "dup3@example.com"
        resp = self.client.post(self.url_register, data)
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        self.assertIn("email", form.errors)

    def test_authenticated_user_redirect(self):
        u = User.objects.create_user(email="logg@in.com", password="x")
        u.is_approved = True
        u.save()
        Patient.objects.create(user=u, full_name="Logged", email=u.email)
        self.client.login(username="logg@in.com", password="x")
        resp = self.client.get(self.url_register)
        self.assertEqual(resp.status_code, 302)


# ------------------------------------------------------------------
# login + redirect tests
# ------------------------------------------------------------------
class ExtendedLoginViewRedirectTest(AccountsBaseCase):
    def setUp(self):
        self.client = Client()

    def _make_user(self, email, role="patient", approved=True, password=None):
        password = password or strong_pass()
        user = User.objects.create_user(email=email, password=password, role=role)
        user.is_approved = approved
        if role == "admin":
            user.is_staff = True
            user.is_superuser = True
        user.save()
        return user, password

    def _ensure_patient(self, user):
        Patient.objects.get_or_create(user=user, defaults={"full_name": user.email, "email": user.email})

    def test_patient_redirect(self):
        user, pwd = self._make_user("redir_patient@example.com", "patient", True)
        self._ensure_patient(user)
        resp = self.client.post(self.url_login, {"username": user.email, "password": pwd})
        self.assertRedirects(resp, self.url_patient_dashboard, fetch_redirect_response=False)

    def test_doctor_redirect(self):
        user, pwd = self._make_user("redir_doc@example.com", "doctor", True)
        resp = self.client.post(self.url_login, {"username": user.email, "password": pwd})
        expected = self.url_doctor_dashboard if self.url_doctor_dashboard != "/" else self.url_home
        self.assertEqual(resp.status_code, 302)
        self.assertIn(expected, resp["Location"])

    def test_secretary_redirect(self):
        user, pwd = self._make_user("redir_sec@example.com", "secretary", True)
        resp = self.client.post(self.url_login, {"username": user.email, "password": pwd})
        expected = self.url_secretary_dashboard if self.url_secretary_dashboard != "/" else self.url_home
        self.assertEqual(resp.status_code, 302)
        self.assertIn(expected, resp["Location"])

    def test_admin_redirect(self):
        user, pwd = self._make_user("redir_admin@example.com", "admin", True)
        resp = self.client.post(self.url_login, {"username": user.email, "password": pwd})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self.url_admin_index, resp["Location"])

    def test_login_with_safe_next(self):
        user, pwd = self._make_user("nextsafe2@example.com", approved=True)
        self._ensure_patient(user)
        resp = self.client.post(
            f"{self.url_login}?next={self.url_home}",
            {"username": user.email, "password": pwd},
        )
        self.assertRedirects(resp, self.url_home, fetch_redirect_response=False)

    def test_login_with_external_next_ignored(self):
        user, pwd = self._make_user("nextevil2@example.com", approved=True)
        self._ensure_patient(user)
        resp = self.client.post(
            f"{self.url_login}?next=http://evil.com",
            {"username": user.email, "password": pwd},
        )
        self.assertRedirects(resp, self.url_patient_dashboard, fetch_redirect_response=False)


# ------------------------------------------------------------------
# staff-login variant
# ------------------------------------------------------------------
class StaffLoginToggleSignupTest(AccountsBaseCase):
    """Verifies that accounts:staff_login (if configured) hides the signup link."""
    def setUp(self):
        self.client = Client()
        try:
            self.url_staff_login = reverse("accounts:staff_login")
            self.has_staff = True
        except NoReverseMatch:
            self.has_staff = False

    def test_staff_login_hides_signup(self):
        if not self.has_staff:
            self.skipTest("accounts:staff_login not configured.")
        resp = self.client.get(self.url_staff_login)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("show_signup", resp.context)
        self.assertFalse(resp.context["show_signup"])


# ------------------------------------------------------------------
# password reset flow
# ------------------------------------------------------------------
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetFlowTest(AccountsBaseCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(email="pwreset@example.com", password=strong_pass())
        self.user.is_approved = True
        self.user.save()
        Patient.objects.create(user=self.user, full_name="PW Reset", email=self.user.email)

    def test_password_reset_sends_email(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

    def test_password_reset_full_flow(self):
        """
        Request reset, then build a valid confirm URL from the user
        (instead of parsing the email body) to keep the test stable.
        We follow Django's redirect from the token URL to the set-password URL.
        """
        # request reset & confirm email sent
        resp = self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertTrue(mail.outbox)

        # build confirm URL (uid/token)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        token_path = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})

        # GET token URL (Django will redirect to set-password/)
        resp = self.client.get(token_path)
        if resp.status_code == 302:
            # follow to set-password URL
            setpwd_path = _rel_from_location(resp["Location"])
            resp = self.client.get(setpwd_path)
        else:
            # some custom setups render form directly
            setpwd_path = token_path
        self.assertEqual(resp.status_code, 200)

        # POST new password to the set-password URL
        new_pass = "NewPass789!"
        resp = self.client.post(setpwd_path, {"new_password1": new_pass, "new_password2": new_pass})
        # should redirect to done
        self.assertRedirects(resp, reverse("accounts:password_reset_complete"))

        # login with new password works
        resp = self.client.post(self.url_login, {"username": self.user.email, "password": new_pass})
        self.assertEqual(resp.status_code, 302)
