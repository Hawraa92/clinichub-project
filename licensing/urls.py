from django.urls import path

from . import views


app_name = "licensing"


urlpatterns = [
    path("", views.license_status, name="status"),
    path("activate/", views.activate_license, name="activate"),
    path(
        "installation-request.json",
        views.installation_request,
        name="installation_request",
    ),
    path("sync/", views.sync_license, name="sync"),
    path("api/status/", views.status_api, name="status_api"),
]
