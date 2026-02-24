# patient/urls.py
from __future__ import annotations

from django.urls import path
from django.views.generic import RedirectView

from . import views
from .diabetes_views import diabetes_predict_view

app_name = "patient"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Patient Self Dashboard (when the patient logs in with their account)
    # ------------------------------------------------------------------ #
    path("dashboard/", views.patient_dashboard, name="dashboard"),

    # ------------------------------------------------------------------ #
    # Diabetes Prediction (Screening)
    # URL: /patient/diabetes/predict/
    # ------------------------------------------------------------------ #
    path("diabetes/predict/", diabetes_predict_view, name="diabetes_predict"),

    # ------------------------------------------------------------------ #
    # Create a New Patient
    # ------------------------------------------------------------------ #
    path("new/", views.create_patient, name="create"),

    # Legacy route for backward compatibility (do NOT remove if old links exist)
    path(
        "create/",
        RedirectView.as_view(pattern_name="patient:create", permanent=False),
        name="create_patient",
    ),

    # ------------------------------------------------------------------ #
    # Patient List (for staff: doctor / secretary)
    # ------------------------------------------------------------------ #
    path("list/", views.patient_list, name="list"),

    # ------------------------------------------------------------------ #
    # Edit Patient
    # ------------------------------------------------------------------ #
    path("<int:pk>/edit/", views.edit_patient, name="edit"),

    # ------------------------------------------------------------------ #
    # Patient Detail
    # ------------------------------------------------------------------ #
    path("<int:pk>/", views.patient_detail, name="detail"),

    # ------------------------------------------------------------------ #
    # Optional Legacy Compatibility Routes (enable only if needed)
    # Note: <int:pk> does not conflict with (dashboard/new/list/...)
    # ------------------------------------------------------------------ #
    # path("", RedirectView.as_view(pattern_name="patient:list", permanent=False), name="index"),
    # path(
    #     "view/<int:pk>/",
    #     RedirectView.as_view(pattern_name="patient:detail", permanent=False),
    #     name="view_legacy",
    # ),
    # path(
    #     "update/<int:pk>/",
    #     RedirectView.as_view(pattern_name="patient:edit", permanent=False),
    #     name="update_legacy",
    # ),

    # ------------------------------------------------------------------ #
    # Delete Patient (enable only after adding a secure delete view)
    # ------------------------------------------------------------------ #
    # path("<int:pk>/delete/", views.delete_patient, name="delete"),
]
