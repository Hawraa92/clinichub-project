from django.urls import path

from . import views


app_name = "ecg"


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),
    path(
        "create/",
        views.create_record,
        name="create_record",
    ),
    path(
        "record/<int:record_id>/",
        views.record_detail,
        name="record_detail",
    ),
]