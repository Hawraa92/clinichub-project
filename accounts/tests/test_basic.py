# accounts/tests/test_basic.py
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from accounts.forms import PatientSignUpForm, ApprovedAuthenticationForm
from patient.models import Patient

User = get_user_model()


class UserManagerTest(TestCase):
    def test_create_user_requires_email(self):
        with self.assertRaisesMessage(ValueError, 'The Email field must be set'):
            User.objects.create_user(email=None, password='test123')

    def test_create_user_patient_approved(self):
        user = User.objects.create_user(email='patient@example.com', password='pass')
        self.assertTrue(user.is_approved)
        self.assertEqual(user.role, 'patient')

    def test_create_user_doctor_not_approved(self):
        user = User.objects.create_user(email='doc@example.com', password='pass', role='doctor')
        self.assertFalse(user.is_approved)
        self.assertEqual(user.role, 'doctor')

    def test_create_superuser(self):
        admin = User.objects.create_superuser(email='admin@example.com', password='adminpass')
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_approved)
        self.assertEqual(admin.role, 'admin')

    def test_create_superuser_role_error(self):
        # الرسالة قد تتغير؛ نتحقق من احتواء كلمة role
        with self.assertRaises(ValueError) as cm:
            User.objects.create_superuser(email='bad@example.com', password='123', role='patient')
        self.assertIn('role', str(cm.exception).lower())


class PatientSignUpFormTest(TestCase):
    def setUp(self):
        self.valid_data = {
            'email': 'newpatient@example.com',
            'username': 'newpatient',
            'password1': 'ComplexPass123!',
            'password2': 'ComplexPass123!'
        }

    def test_valid_form_creates_user_and_patient(self):
        form = PatientSignUpForm(data=self.valid_data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.email, 'newpatient@example.com')
        self.assertEqual(user.role, 'patient')
        self.assertTrue(user.is_approved)
        # Patient NOT auto-created by form (created in the register view).
        self.assertFalse(Patient.objects.filter(user=user).exists())

    def test_duplicate_email(self):
        User.objects.create_user(email='dup@example.com', password='test')
        form = PatientSignUpForm(data={**self.valid_data, 'email': 'dup@example.com'})
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)


class ApprovedAuthenticationFormTest(TestCase):
    def setUp(self):
        # create unapproved user
        self.user = User.objects.create_user(email='user1@example.com', password='pass')
        self.user.is_approved = False
        self.user.save()

    def test_block_unapproved(self):
        # request=None works fine for form-level test
        form = ApprovedAuthenticationForm(None, data={'username': 'user1@example.com', 'password': 'pass'})
        self.assertFalse(form.is_valid())
        # Ensure *some* non-field error was raised
        self.assertTrue(form.non_field_errors())

    def test_allow_approved(self):
        self.user.is_approved = True
        self.user.save()
        form = ApprovedAuthenticationForm(None, data={'username': 'user1@example.com', 'password': 'pass'})
        self.assertTrue(form.is_valid(), form.errors)


class AccountsViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.register_url = reverse('accounts:register')
        self.login_url = reverse('accounts:login')
        self.logout_url = reverse('accounts:logout')
        # create patient credentials
        self.credentials = {
            'email': 'test2@example.com',
            'username': 'test2',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!'
        }

    def test_register_get(self):
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/register.html')

    def test_register_post_valid(self):
        response = self.client.post(self.register_url, self.credentials)
        self.assertRedirects(response, self.login_url)
        user = User.objects.get(email='test2@example.com')
        self.assertTrue(Patient.objects.filter(user=user).exists())

    def test_register_duplicate_email(self):
        User.objects.create_user(email='dup2@example.com', password='test')
        payload = {**self.credentials, 'email': 'dup2@example.com'}
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, 200)  # stayed on page
        form = response.context['form']
        self.assertIn('email', form.errors)

    def test_login_get(self):
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_login_post_valid(self):
        # first create and approve user
        user = User.objects.create_user(email='loginuser@example.com', password='pass123')
        user.is_approved = True
        user.save()
        response = self.client.post(self.login_url, {'username': 'loginuser@example.com', 'password': 'pass123'})
        self.assertEqual(response.status_code, 302)  # redirect somewhere

    def test_logout(self):
        # simulate login
        user = User.objects.create_user(email='logoutuser@example.com', password='pass123')
        user.is_approved = True
        user.save()
        self.client.login(username='logoutuser@example.com', password='pass123')
        response = self.client.get(self.logout_url)
        self.assertRedirects(response, self.login_url)
