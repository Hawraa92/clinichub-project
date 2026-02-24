# accounts/urls.py
from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

from .views import register, login_view, logout_view

app_name = "accounts"

LOGIN_SHOW_SIGNUP = {"show_signup": True}
LOGIN_HIDE_SIGNUP = {"show_signup": False}

urlpatterns = [
    # Optional: /accounts/ -> /accounts/login/
    path(
        "",
        RedirectView.as_view(pattern_name="accounts:login", permanent=False),
        name="index",
    ),

    # -----------------------------
    # 1) Patient public registration
    # -----------------------------
    path("register/", register, name="register"),

    # ---------------------------------------
    # 2) Unified login (alias routes supported)
    # ---------------------------------------
    path("login/", login_view, LOGIN_SHOW_SIGNUP, name="login"),
    path("patient-login/", login_view, LOGIN_SHOW_SIGNUP, name="patient_login"),

    # Staff login without signup link
    path("staff-login/", login_view, LOGIN_HIDE_SIGNUP, name="staff_login"),

    # 3) Logout
    path("logout/", logout_view, name="logout"),

    # -------------------------------------------------
    # 4) Password reset (email flow) ✅ HTML + TXT
    # -------------------------------------------------
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",

            # ✅ TXT fallback (works even if email client blocks HTML)
            email_template_name="registration/password_reset_email.txt",

            # ✅ HTML version (nice UI in Gmail)
            html_email_template_name="registration/password_reset_email.html",

            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),

    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),

    # ✅ This name MUST exist because the email template reverses it:
    # {% url 'accounts:password_reset_confirm' uidb64=uid token=token %}
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),

    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
]
