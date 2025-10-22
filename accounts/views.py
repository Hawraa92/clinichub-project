# accounts/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.db import transaction, IntegrityError
from django.http import HttpResponseNotAllowed  # لرفض GET في الإنتاج على logout

from .forms import PatientSignUpForm, ApprovedAuthenticationForm
from patient.models import Patient


def get_redirect_url_for_user(user):
    """
    Return the appropriate dashboard URL based on the user's role/superuser status.
    """
    # Platform superusers → Django Admin
    if user.is_superuser or getattr(user, 'role', None) == 'admin':
        return reverse('admin:index')

    # Role-based redirects (ensure these names exist in your URLconf)
    role_redirects = {
        'patient': reverse('patient:dashboard'),
        'doctor': reverse('doctor:dashboard'),
        'secretary': reverse('appointments:secretary_dashboard'),
    }
    return role_redirects.get(getattr(user, 'role', None), reverse('home:index'))


def _get_safe_next(request, fallback):
    """
    Safely resolve ?next= redirect target (internal URLs only).
    Accepts relative paths and hosts listed in ALLOWED_HOSTS.
    """
    next_url = request.POST.get('next') or request.GET.get('next')
    if not next_url:
        return fallback

    # اجمع كل المضيفين المسموح بهم + المضيف الحالي (يغطي بيئات متعددة مثل Render ودومين مخصص)
    allowed = set(settings.ALLOWED_HOSTS or [])
    allowed.add(request.get_host())

    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts=allowed,
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


@require_http_methods(["GET", "POST"])
def register(request):
    """
    Public patient self-registration.
    Authenticated users are redirected to their dashboards.
    """
    if request.user.is_authenticated:
        messages.warning(
            request,
            _("Registration is restricted to new patients. Redirecting to your dashboard.")
        )
        return redirect(get_redirect_url_for_user(request.user))

    if request.method == 'POST':
        form = PatientSignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Save user but delay commit inside transaction
                    user = form.save(commit=False)
                    user.save()

                    # Ensure a Patient record exists (avoid duplicates under race)
                    full_name = user.get_full_name() or user.username or user.email
                    Patient.objects.get_or_create(
                        user=user,
                        defaults={'full_name': full_name, 'email': user.email}
                    )
            except IntegrityError:
                messages.error(
                    request,
                    _("We could not create your patient account. Please try again.")
                )
            else:
                messages.success(
                    request,
                    _("Your patient account has been created successfully! You may now log in.")
                )
                return redirect(reverse_lazy('accounts:login'))
        else:
            messages.error(request, _("Please correct the errors below."))
    else:
        form = PatientSignUpForm()

    return render(request, 'accounts/register.html', {'form': form})


@require_http_methods(["GET", "POST"])
def login_view(request, show_signup=True):
    """
    Unified email-based login for all roles.
    Blocks unapproved users via ApprovedAuthenticationForm.
    Supports ?next= redirect.
    """
    if request.user.is_authenticated:
        return redirect(get_redirect_url_for_user(request.user))

    # Always pass request to AuthenticationForm (required for some backends)
    form = ApprovedAuthenticationForm(request=request, data=request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, _("You have successfully logged in."))
            fallback = get_redirect_url_for_user(user)
            return redirect(_get_safe_next(request, fallback))
        else:
            # Let form errors show specifics (invalid creds vs not approved)
            messages.error(request, _("Please correct the errors below."))

    context = {'form': form, 'show_signup': show_signup}
    return render(request, 'accounts/login.html', context)


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Log out current user and redirect to login page.

    سياسة الأمان:
    - في التطوير (DEBUG=True): نسمح بـ GET لتسهيل العمل.
    - في الإنتاج (DEBUG=False): نرفض GET ونشترط POST لحماية من هجمات CSRF على روابط الخروج.
    """
    if request.method != "POST" and not settings.DEBUG:
        return HttpResponseNotAllowed(permitted_methods=["POST"])

    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect(reverse_lazy('accounts:login'))
