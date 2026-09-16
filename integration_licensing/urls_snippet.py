"""
Add this path to ClinicHub/urls.py inside urlpatterns.
"""

from django.urls import include, path


urlpatterns += [
    path(
        "licensing/",
        include(("licensing.urls", "licensing"), namespace="licensing"),
    ),
]
