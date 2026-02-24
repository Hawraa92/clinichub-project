# home/views.py
from __future__ import annotations

from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse

from doctor.models import Doctor


LAB_ROLES = {"lab", "laboratory", "lab_tech", "lab_staff"}


def home_view(request):
    """
    Home page behavior:
    - Anonymous users: show public landing page.
    - Authenticated users: redirect to their role dashboard مباشرة
      (حتى ما يصير لخبطة بالواجهة، وخصوصاً لأن home.html يعرض Quick Actions لأي logged-in user).
    """

    if request.user.is_authenticated:
        role = (getattr(request.user, "role", "") or "").lower()

        # Superuser/Admin
        if request.user.is_superuser or role == "admin":
            return redirect("admin:index")

        # Doctor
        if role == "doctor":
            return redirect("doctor:dashboard")

        # Secretary
        if role == "secretary":
            return redirect("appointments:secretary_dashboard")

        # Lab
        if role in LAB_ROLES:
            return redirect("lab:dashboard")

        # Patient
        if role == "patient":
            return redirect("patient:dashboard")

        # Unknown role -> go to login (or keep home)
        return redirect("accounts:login")

    # Anonymous -> landing
    context = {
        "now": timezone.now(),
    }
    return render(request, "home/home.html", context)
