# accounts/urls.py

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.views.generic import RedirectView

from .permissions_views import (
    permissions_dashboard,
    user_permissions_edit,
)
from .views import (
    login_view,
    logout_view,
    register,
)


app_name = "accounts"


LOGIN_SHOW_SIGNUP = {
    "show_signup": True,
}

LOGIN_HIDE_SIGNUP = {
    "show_signup": False,
}


urlpatterns = [
    # -------------------------------------------------
    # 1) Accounts index
    # /accounts/ -> /accounts/login/
    # -------------------------------------------------
    path(
        "",
        RedirectView.as_view(
            pattern_name="accounts:login",
            permanent=False,
        ),
        name="index",
    ),

    # -------------------------------------------------
    # 2) Patient public registration
    # -------------------------------------------------
    path(
        "register/",
        register,
        name="register",
    ),

    # -------------------------------------------------
    # 3) Unified login
    # -------------------------------------------------
    path(
        "login/",
        login_view,
        LOGIN_SHOW_SIGNUP,
        name="login",
    ),

    path(
        "patient-login/",
        login_view,
        LOGIN_SHOW_SIGNUP,
        name="patient_login",
    ),

    # Staff login without signup link
    path(
        "staff-login/",
        login_view,
        LOGIN_HIDE_SIGNUP,
        name="staff_login",
    ),

    # -------------------------------------------------
    # 4) Logout
    # -------------------------------------------------
    path(
        "logout/",
        logout_view,
        name="logout",
    ),

    # -------------------------------------------------
    # 5) Super Admin permissions management
    # -------------------------------------------------

    # قائمة المستخدمين وإدارة الصلاحيات
    path(
        "permissions/",
        permissions_dashboard,
        name="permissions_dashboard",
    ),

    # تعديل صلاحيات مستخدم محدد
    path(
        "permissions/users/<int:user_id>/",
        user_permissions_edit,
        name="user_permissions_edit",
    ),

    # -------------------------------------------------
    # 6) Password reset
    # HTML + TXT email flow
    # -------------------------------------------------
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name=(
                "registration/"
                "password_reset_form.html"
            ),

            # TXT fallback
            email_template_name=(
                "registration/"
                "password_reset_email.txt"
            ),

            # HTML email
            html_email_template_name=(
                "registration/"
                "password_reset_email.html"
            ),

            subject_template_name=(
                "registration/"
                "password_reset_subject.txt"
            ),

            success_url=reverse_lazy(
                "accounts:password_reset_done"
            ),
        ),
        name="password_reset",
    ),

    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name=(
                "registration/"
                "password_reset_done.html"
            ),
        ),
        name="password_reset_done",
    ),

    # هذا الاسم مطلوب داخل رسالة إعادة تعيين كلمة المرور:
    #
    # {% url 'accounts:password_reset_confirm'
    #     uidb64=uid token=token %}
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name=(
                "registration/"
                "password_reset_confirm.html"
            ),

            success_url=reverse_lazy(
                "accounts:password_reset_complete"
            ),
        ),
        name="password_reset_confirm",
    ),

    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name=(
                "registration/"
                "password_reset_complete.html"
            ),
        ),
        name="password_reset_complete",
    ),
]