# accounts/views.py
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.db import IntegrityError, transaction
from django.http.request import split_domain_port
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from .forms import ApprovedAuthenticationForm, PatientSignUpForm
from patient.models import Patient


def _safe_reverse(name: str, fallback_name: str = "home:index", final_fallback: str = "/") -> str:
    """
    Reverse URL safely:
    - try reverse(name)
    - else try reverse(fallback_name)
    - else return final_fallback ("/")
    """
    try:
        return reverse(name)
    except Exception:
        try:
            return reverse(fallback_name)
        except Exception:
            return final_fallback


def _strip_port(host: str) -> str:
    """
    Return host without port, safe for IPv4/IPv6.
    Examples:
    - "example.com:8000" -> "example.com"
    - "[::1]:8000" -> "::1"
    """
    host = (host or "").strip()
    if not host:
        return ""
    domain, _port = split_domain_port(host)
    domain = (domain or "").strip()
    # split_domain_port may return "[::1]" for IPv6
    if domain.startswith("[") and domain.endswith("]"):
        domain = domain[1:-1]
    return domain


def get_redirect_url_for_user(user) -> str:
    """
    Return the appropriate dashboard URL based on the user's role/superuser status.
    """
    if user.is_superuser or getattr(user, "role", None) == "admin":
        return _safe_reverse("admin:index", fallback_name="home:index")

    role = getattr(user, "role", None)

    role_redirects = {
        "patient": _safe_reverse("patient:dashboard"),
        "doctor": _safe_reverse("doctor:dashboard"),
        "secretary": _safe_reverse("appointments:secretary_dashboard"),
        "lab": _safe_reverse("lab:dashboard"),
        # tolerances (if legacy values exist somewhere)
        "laboratory": _safe_reverse("lab:dashboard"),
        "lab_tech": _safe_reverse("lab:dashboard"),
        "lab_staff": _safe_reverse("lab:dashboard"),
    }
    return role_redirects.get(role, _safe_reverse("home:index"))


def _get_safe_next(request, fallback: str) -> str:
    """
    Safely resolve ?next= redirect target.

    Rules:
    - Allow safe relative paths like "/x" (block "//evil.com")
    - Block loops to login/register
    - For absolute URLs, allow only same-site (validated via url_has_allowed_host_and_scheme)
    """
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if not next_url:
        return fallback

    # prevent loops to login/register (even with querystring)
    login_path = str(reverse_lazy("accounts:login"))
    register_path = str(reverse_lazy("accounts:register"))
    if next_url.startswith(login_path) or next_url.startswith(register_path):
        return fallback

    # ✅ If it's a normal internal path, allow it (most secure + simplest)
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    # Otherwise validate absolute URL against allowed hosts
    allowed_hosts: set[str] = set()
    request_host = _strip_port(request.get_host())

    if getattr(settings, "ALLOWED_HOSTS", None) == ["*"]:
        if request_host:
            allowed_hosts.add(request_host)
    else:
        for h in (settings.ALLOWED_HOSTS or []):
            h = _strip_port(h)
            if not h or h == "*":
                continue
            # ".example.com" means subdomains allowed; best-effort here:
            # accept the base domain too to avoid false negatives.
            if h.startswith("."):
                allowed_hosts.add(h.lstrip("."))
            else:
                allowed_hosts.add(h)
        if request_host:
            allowed_hosts.add(request_host)

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
    Public patient self-registration.
    Authenticated users are redirected to their dashboards.
    """
    if request.user.is_authenticated:
        messages.warning(
            request,
            _("Registration is restricted to new patients. Redirecting to your dashboard."),
        )
        return redirect(get_redirect_url_for_user(request.user))

    if request.method == "POST":
        form = PatientSignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)

                    # ✅ Force patient role (no bypass)
                    if hasattr(user, "role"):
                        user.role = "patient"

                    # ✅ Make patient immediately usable
                    if hasattr(user, "is_approved"):
                        user.is_approved = True

                    user.save()

                    full_name = user.get_full_name() or user.username or user.email

                    # Ensure Patient profile exists (idempotent)
                    Patient.objects.get_or_create(
                        user=user,
                        defaults={"full_name": full_name, "email": user.email},
                    )

            except IntegrityError:
                messages.error(request, _("We could not create your patient account. Please try again."))
            else:
                messages.success(request, _("Your patient account has been created successfully! You may now log in."))
                return redirect(reverse_lazy("accounts:login"))
        else:
            messages.error(request, _("Please correct the errors below."))
    else:
        form = PatientSignUpForm()

    return render(request, "accounts/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_view(request, show_signup: bool = True):
    """
    Unified email-based login for all roles.
    Blocks unapproved users via ApprovedAuthenticationForm.
    Supports ?next= redirect (secure).
    """
    if request.user.is_authenticated:
        return redirect(get_redirect_url_for_user(request.user))

    form = ApprovedAuthenticationForm(request=request, data=(request.POST or None))

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, _("You have successfully logged in."))

            fallback = get_redirect_url_for_user(user)
            return redirect(_get_safe_next(request, fallback))

        messages.error(request, _("Please correct the errors below."))

    return render(request, "accounts/login.html", {"form": form, "show_signup": show_signup})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Log out current user and redirect to login page.

    ✅ Tests expect GET to work and redirect (302), so we allow both GET and POST.
    """
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect(reverse_lazy("accounts:login"))