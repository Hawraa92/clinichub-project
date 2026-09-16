# patient/diabetes_views.py
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .diabetes_forms import DiabetesRiskForm
from .ml.diabetes_predictor import predict_diabetes


@login_required
def diabetes_predict_view(request):
    """
    Diabetes screening page (not a final diagnosis).
    URL: /patient/diabetes/predict/
    """
    result = None

    if request.method == "POST":
        form = DiabetesRiskForm(request.POST)
        if form.is_valid():
            result = predict_diabetes(form.cleaned_data)
    else:
        form = DiabetesRiskForm()

    return render(
        request,
        "patient/diabetes_predict.html",
        {"form": form, "result": result},
    )
