from django.urls import path

from . import views


app_name = "analytics"


urlpatterns = [
    # لوحة التحليلات المركزية
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    # تفاصيل وتحليلات فرع محدد
    path(
        "branch/<int:branch_id>/",
        views.branch_detail,
        name="branch_detail",
    ),
]