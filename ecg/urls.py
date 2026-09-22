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
    path(
        "record/<int:record_id>/upload/",
        views.upload_file,
        name="upload_file",
    ),
    path(
        "record/<int:record_id>/file/<int:file_id>/download/",
        views.download_file,
        name="download_file",
    ),
]