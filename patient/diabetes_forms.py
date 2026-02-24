# patient/diabetes_forms.py
from __future__ import annotations

from django import forms

YES_NO = [(0, "No"), (1, "Yes")]
SEX_CHOICES = [(0, "Female"), (1, "Male")]


class DiabetesRiskForm(forms.Form):
    """
    Input form for the diabetes screening model (BRFSS-style features).
    Must match the FEATURES list in patient/ml/diabetes_predictor.py
    """

    # -------------------------
    # Binary (0/1) fields
    # -------------------------
    HighBP = forms.TypedChoiceField(label="High Blood Pressure", choices=YES_NO, coerce=int, initial=0)
    HighChol = forms.TypedChoiceField(label="High Cholesterol", choices=YES_NO, coerce=int, initial=0)
    CholCheck = forms.TypedChoiceField(label="Cholesterol Check (past 5 years)", choices=YES_NO, coerce=int, initial=0)
    Smoker = forms.TypedChoiceField(label="Smoker", choices=YES_NO, coerce=int, initial=0)
    Stroke = forms.TypedChoiceField(label="History of Stroke", choices=YES_NO, coerce=int, initial=0)
    HeartDiseaseorAttack = forms.TypedChoiceField(label="Heart Disease or Heart Attack", choices=YES_NO, coerce=int, initial=0)
    PhysActivity = forms.TypedChoiceField(label="Physical Activity", choices=YES_NO, coerce=int, initial=0)
    Fruits = forms.TypedChoiceField(label="Eats Fruits", choices=YES_NO, coerce=int, initial=0)
    Veggies = forms.TypedChoiceField(label="Eats Vegetables", choices=YES_NO, coerce=int, initial=0)
    HvyAlcoholConsump = forms.TypedChoiceField(label="Heavy Alcohol Consumption", choices=YES_NO, coerce=int, initial=0)
    AnyHealthcare = forms.TypedChoiceField(label="Has Any Healthcare Coverage", choices=YES_NO, coerce=int, initial=0)
    NoDocbcCost = forms.TypedChoiceField(label="Could Not See Doctor Because of Cost", choices=YES_NO, coerce=int, initial=0)
    DiffWalk = forms.TypedChoiceField(label="Difficulty Walking", choices=YES_NO, coerce=int, initial=0)

    Sex = forms.TypedChoiceField(label="Sex", choices=SEX_CHOICES, coerce=int, initial=0)

    # -------------------------
    # Numeric / ordinal fields
    # -------------------------
    BMI = forms.FloatField(label="BMI", min_value=10, max_value=100, initial=25)

    GenHlth = forms.IntegerField(label="General Health (1=Excellent .. 5=Poor)", min_value=1, max_value=5, initial=3)
    MentHlth = forms.IntegerField(label="Mental Health Days (0..30)", min_value=0, max_value=30, initial=0)
    PhysHlth = forms.IntegerField(label="Physical Health Days (0..30)", min_value=0, max_value=30, initial=0)

    Age = forms.IntegerField(label="Age Category (1..13)", min_value=1, max_value=13, initial=7)
    Education = forms.IntegerField(label="Education Level (1..6)", min_value=1, max_value=6, initial=4)
    Income = forms.IntegerField(label="Income Level (1..8)", min_value=1, max_value=8, initial=4)
