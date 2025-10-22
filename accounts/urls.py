# accounts/urls.py
from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from .views import register, login_view, logout_view

app_name = 'accounts'

urlpatterns = [
    # -----------------------------
    # 1. Patient public registration
    # -----------------------------
    path(
        'register/',
        register,
        name='register'
    ),

    # ---------------------------------------
    # 2. Unified login (alias routes supported)
    #    show_signup=True => يعرض رابط "إنشاء حساب"
    # ---------------------------------------
    path(
        'login/',
        login_view,
        kwargs={'show_signup': True},
        name='login'
    ),
    path(
        'patient-login/',
        login_view,
        kwargs={'show_signup': True},  # مستخدم في home.html
        name='patient_login'
    ),

    # ------------------------------------------------
    # 2b. (اختياري) تسجيل دخول الطاقم بدون رابط تسجيل
    # ------------------------------------------------
    path(
        'staff-login/',
        login_view,
        kwargs={'show_signup': False},
        name='staff_login'
    ),

    # 3. Logout
    path(
        'logout/',
        logout_view,
        name='logout'
    ),

    # -------------------------------------------------
    # 4. Password reset (flow عبر البريد - نسيان كلمة المرور)
    # مسارات Django القياسية مع قوالب مخصصة
    # -------------------------------------------------

    # طلب إعادة ضبط
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset'
    ),

    # تم إرسال البريد
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done'
    ),

    # رابط من البريد (uid + token)
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm'
    ),

    # الاكتمال النهائي
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete'
    ),
]
