from django.urls import path

from . import views


app_name = "ecg"


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),
]