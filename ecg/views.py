from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .access import ecg_form_querysets_for_user
from .forms import ECGRecordForm


@login_required
def dashboard(request):
    return render(request, "ecg/dashboard.html")


@login_required
def create_record(request):
    if not request.user.has_perm("ecg.add_ecgrecord"):
        raise PermissionDenied

    form = ECGRecordForm(
        request.POST or None,
        **ecg_form_querysets_for_user(request.user),
    )

    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.created_by = request.user
        record.save()

        messages.success(
            request,
            "ECG record created successfully.",
        )

        return redirect("ecg:dashboard")

    return render(
        request,
        "ecg/create_record.html",
        {
            "form": form,
        },
    )