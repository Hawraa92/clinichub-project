# accounts/views.py
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.db import IntegrityError, transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from patient.models import Patient

from .forms import ApprovedAuthenticationForm, PatientSignUpForm


def _safe_reverse(name: str, fallback_name: str = "home:index") -> str:
    """
    Reverse a URL safely and return the fallback URL if the route is unavailable.
    """
    try:
        return reverse(name)
    except NoReverseMatch:
        return reverse(fallback_name)


def get_redirect_url_for_user(user) -> str:
    """
    Return the appropriate dashboard URL based on the authenticated user's role.
    """
    if user.is_superuser or getattr(user, "role", None) == "admin":
        return _safe_reverse(
            "admin:index",
            fallback_name="home:index",
        )

    role = str(getattr(user, "role", "") or "").strip().lower()

    role_redirects = {
        "patient": "patient:dashboard",
        "doctor": "doctor:dashboard",
        "secretary": "appointments:secretary_dashboard",
        "lab": "lab:dashboard",
        "laboratory": "lab:dashboard",
        "lab_tech": "lab:dashboard",
        "lab_staff": "lab:dashboard",
        "pharmacist": "pharmacy:dashboard",
        "pharmacy": "pharmacy:dashboard",
        "pharmacy_staff": "pharmacy:dashboard",
    }

    route_name = role_redirects.get(role)

    if route_name:
        return _safe_reverse(
            route_name,
            fallback_name="home:index",
        )

    return _safe_reverse("home:index")


def _get_safe_next(request, fallback: str) -> str:
    """
    Resolve the requested next URL safely.

    Home, login and registration URLs are ignored to prevent redirect loops.
    Only internal URLs belonging to an allowed host are accepted.
    """
    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or ""
    ).strip()

    if not next_url:
        return fallback

    try:
        home_path = reverse("home:index")
    except NoReverseMatch:
        home_path = "/"

    if next_url in {"/", home_path}:
        return fallback

    login_path = str(reverse_lazy("accounts:login"))
    register_path = str(reverse_lazy("accounts:register"))

    if (
        next_url.startswith(login_path)
        or next_url.startswith(register_path)
    ):
        return fallback

    allowed_hosts = {request.get_host()}

    configured_hosts = getattr(settings, "ALLOWED_HOSTS", []) or []

    if configured_hosts != ["*"]:
        for host in configured_hosts:
            host = str(host or "").strip()

            if host and host != "*":
                allowed_hosts.add(host)

    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts=allowed_hosts,
        require_https=request.is_secure(),
    ):
        return next_url

    return fallback


@require_http_methods(["GET", "POST"])
def register(request):
    """
    Register a new patient account.
    """
    if request.user.is_authenticated:
        messages.warning(
            request,
            _(
                "Registration is restricted to new patients. "
                "Redirecting to your dashboard."
            ),
        )
        return redirect(
            get_redirect_url_for_user(request.user)
        )

    if request.method == "POST":
        form = PatientSignUpForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.save()

                    full_name = (
                        user.get_full_name()
                        or user.username
                        or user.email
                    )

                    Patient.objects.get_or_create(
                        user=user,
                        defaults={
                            "full_name": full_name,
                            "email": user.email,
                        },
                    )

            except IntegrityError:
                messages.error(
                    request,
                    _(
                        "We could not create your patient account. "
                        "Please try again."
                    ),
                )

            else:
                messages.success(
                    request,
                    _(
                        "Your patient account has been created successfully! "
                        "You may now log in."
                    ),
                )
                return redirect(
                    reverse_lazy("accounts:login")
                )

        else:
            messages.error(
                request,
                _("Please correct the errors below."),
            )

    else:
        form = PatientSignUpForm()

    context = {
        "form": form,
    }

    return render(
        request,
        "accounts/register.html",
        context,
    )


@require_http_methods(["GET", "POST"])
def login_view(request, show_signup: bool = True):
    """
    Authenticate users and redirect them to the correct role dashboard.
    """
    if request.user.is_authenticated:
        return redirect(
            get_redirect_url_for_user(request.user)
        )

    form = ApprovedAuthenticationForm(
        request=request,
        data=request.POST or None,
    )

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()

            login(request, user)

            messages.success(
                request,
                _("You have successfully logged in."),
            )

            fallback = get_redirect_url_for_user(user)
            destination = _get_safe_next(
                request,
                fallback,
            )

            return redirect(destination)

        messages.error(
            request,
            _("Please correct the errors below."),
        )

    context = {
        "form": form,
        "show_signup": show_signup,
    }

    return render(
        request,
        "accounts/login.html",
        context,
    )


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Log out the current user and redirect to the login page.
    """
    if request.method != "POST" and not settings.DEBUG:
        return HttpResponseNotAllowed(
            permitted_methods=["POST"]
        )

    logout(request)

    messages.info(
        request,
        _("You have been logged out."),
    )

    return redirect(
        reverse_lazy("accounts:login")
    )