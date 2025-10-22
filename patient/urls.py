# patient/urls.py
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "patient"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # لوحة المريض الذاتية (عند دخول المريض بحسابه الشخصي)
    # ------------------------------------------------------------------ #
    path("dashboard/", views.patient_dashboard, name="dashboard"),

    # ------------------------------------------------------------------ #
    # إنشاء مريض جديد
    # ------------------------------------------------------------------ #
    path("new/", views.create_patient, name="create"),

    # مسار قديم للتوافق مع روابط سابقة (لا تحذفه إذا كان هناك روابط قديمة)
    path(
        "create/",
        RedirectView.as_view(pattern_name="patient:create", permanent=False),
        name="create_patient",
    ),

    # ------------------------------------------------------------------ #
    # قائمة المرضى (للكادر الطبي: دكتور / سكرتير)
    # ------------------------------------------------------------------ #
    path("list/", views.patient_list, name="list"),

    # ------------------------------------------------------------------ #
    # تعديل بيانات المريض
    # ------------------------------------------------------------------ #
    path("<int:pk>/edit/", views.edit_patient, name="edit"),

    # ------------------------------------------------------------------ #
    # تفاصيل المريض
    # ------------------------------------------------------------------ #
    path("<int:pk>/", views.patient_detail, name="detail"),

    # ------------------------------------------------------------------ #
    # مسارات توافقية اختيارية — استخدمها إذا عندك روابط قديمة
    # ------------------------------------------------------------------ #
    # path("", RedirectView.as_view(pattern_name="patient:list", permanent=False), name="index"),
    # path("view/<int:pk>/", RedirectView.as_view(pattern_name="patient:detail", permanent=False)),
    # path("update/<int:pk>/", RedirectView.as_view(pattern_name="patient:edit", permanent=False)),

    # ------------------------------------------------------------------ #
    # حذف مريض (فعّلها عند إضافة View للحذف مع الصلاحيات المناسبة)
    # ------------------------------------------------------------------ #
    # path("<int:pk>/delete/", views.delete_patient, name="delete"),
]
