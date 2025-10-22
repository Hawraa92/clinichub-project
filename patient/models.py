"""
patient/models.py
Refactored 06-Aug-2025 — cleansed, validated, ML-friendly, DB-hardened
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower  # case-insensitive indexes/constraints
from django.utils.translation import gettext_lazy as _

# ------------------------------------------------------------------ #
#                      Optional: phonenumbers                         #
# ------------------------------------------------------------------ #
try:
    import phonenumbers as _pn  # type: ignore
    _HAS_PN: Final[bool] = True
except ImportError:  # pragma: no cover
    _HAS_PN = False

MOBILE_REGEX = re.compile(r"^\+?\d{7,15}$")


def validate_mobile(value: str) -> None:
    """E.164-like phone validator (+ optional, 7–15 digits)."""
    if value and not MOBILE_REGEX.match(value):
        raise ValidationError(
            _("%(value)s is not a valid phone number."),
            params={"value": value},
        )


def validate_dob(value) -> None:  # noqa: ANN001
    if value and value > date.today():
        raise ValidationError(_("Date of birth cannot be in the future."))


# ------------------------------------------------------------------ #
#                         Enumerated Choices                          #
# ------------------------------------------------------------------ #
class Sex(models.TextChoices):
    MALE = "M", _("Male")
    FEMALE = "F", _("Female")


class YesNo(models.IntegerChoices):
    NO = 0, _("No")
    YES = 1, _("Yes")


class DiabetesStatus(models.IntegerChoices):
    HEALTHY = 0, _("Healthy")
    PREDIABETIC = 1, _("Prediabetic")
    DIABETIC = 2, _("Diabetic")


class GeneralHealth(models.IntegerChoices):
    EXCELLENT = 1, _("Excellent")
    VERY_GOOD = 2, _("Very good")
    GOOD = 3, _("Good")
    FAIR = 4, _("Fair")
    POOR = 5, _("Poor")


class AgeGroup(models.IntegerChoices):
    AGE_18_24 = 1, _("18–24")
    AGE_25_29 = 2, _("25–29")
    AGE_30_34 = 3, _("30–34")
    AGE_35_39 = 4, _("35–39")
    AGE_40_44 = 5, _("40–44")
    AGE_45_49 = 6, _("45–49")
    AGE_50_54 = 7, _("50–54")
    AGE_55_59 = 8, _("55–59")
    AGE_60_64 = 9, _("60–64")
    AGE_65_69 = 10, _("65–69")
    AGE_70_74 = 11, _("70–74")
    AGE_75_79 = 12, _("75–79")
    AGE_80_PLUS = 13, _("80+")


class EducationLevel(models.IntegerChoices):
    NONE = 1, _("Never attended / Kindergarten only")
    PRIMARY = 2, _("Primary school")
    MIDDLE = 3, _("Middle school")
    HIGH = 4, _("High school")
    VOCATIONAL = 5, _("Vocational / Associate degree")
    COLLEGE = 6, _("College 4yrs+")


class IncomeLevel(models.IntegerChoices):
    UNDER_10K = 1, _("< $10 000")
    TEN_TO_FIFTEEN_K = 2, _("$10 000–14 999")
    FIFTEEN_TO_TWENTY_K = 3, _("$15 000–19 999")
    TWENTY_TO_TWENTYFIVE_K = 4, _("$20 000–24 999")
    TWENTYFIVE_TO_THIRTYFIVE_K = 5, _("$25 000–34 999")
    THIRTYFIVE_TO_FIFTY_K = 6, _("$35 000–49 999")
    FIFTY_TO_SEVENTYFIVE_K = 7, _("$50 000–74 999")
    OVER_75K = 8, _("≥ $75 000")


# ------------------------------------------------------------------ #
#                               Model                                 #
# ------------------------------------------------------------------ #
class Patient(models.Model):
    """Primary patient record. One-to-one optional with AUTH_USER."""

    # --- account linkage ---
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_profile",
        verbose_name=_("User Account"),
        blank=True,
        null=True,
    )

    # --- identity ---
    full_name = models.CharField(_("Full Name"), max_length=100, db_index=True)
    date_of_birth = models.DateField(
        _("Date of Birth"),
        blank=True,
        null=True,
        validators=[validate_dob],
        db_index=True,
    )
    mobile = models.CharField(
        _("Mobile Number"),
        max_length=20,
        validators=[validate_mobile],
        blank=True,
        null=True,
        db_index=True,
        help_text=_("E.164 format: optional +, 7–15 digits."),
    )
    address = models.CharField(_("Address"), max_length=255, blank=True, null=True)
    email = models.EmailField(_("Email Address"), max_length=100, blank=True, null=True)

    # --- clinical baseline ---
    diabetes_status = models.IntegerField(
        _("Diabetes Status"),
        choices=DiabetesStatus.choices,
        blank=True,
        null=True,
        help_text=_("0=Healthy, 1=Prediabetic, 2=Diabetic"),
    )
    high_bp = models.IntegerField(_("High Blood Pressure?"), choices=YesNo.choices, default=0)
    high_chol = models.IntegerField(_("High Cholesterol?"), choices=YesNo.choices, default=0)
    chol_check = models.IntegerField(_("Cholesterol Checked?"), choices=YesNo.choices, default=0)

    bmi = models.DecimalField(
        _("BMI"),
        max_digits=4,
        decimal_places=1,
        blank=True,
        null=True,
        validators=[MinValueValidator(10), MaxValueValidator(80)],
    )
    hbA1c = models.DecimalField(
        _("HbA1c (%)"),
        max_digits=4,
        decimal_places=1,
        blank=True,
        null=True,
        validators=[MinValueValidator(3), MaxValueValidator(15)],
        help_text=_("Average blood glucose (3-month)."),
    )

    smoker = models.IntegerField(_("Smoker?"), choices=YesNo.choices, default=0)
    stroke = models.IntegerField(_("Stroke?"), choices=YesNo.choices, default=0)
    heart_disease_or_attack = models.IntegerField(
        _("Heart Disease or Attack?"), choices=YesNo.choices, default=0
    )
    phys_activity = models.IntegerField(_("Physical Activity?"), choices=YesNo.choices, default=0)
    fruits = models.IntegerField(_("Eats Fruits Regularly?"), choices=YesNo.choices, default=0)
    veggies = models.IntegerField(_("Eats Vegetables Regularly?"), choices=YesNo.choices, default=0)
    hvy_alcohol_consump = models.IntegerField(
        _("Heavy Alcohol Consumption?"), choices=YesNo.choices, default=0
    )
    any_healthcare = models.IntegerField(
        _("Any Healthcare Coverage?"), choices=YesNo.choices, default=0
    )
    no_doc_bc_cost = models.IntegerField(
        _("Could Not See Doctor Due to Cost?"), choices=YesNo.choices, default=0
    )
    gen_hlth = models.IntegerField(
        _("General Health"), choices=GeneralHealth.choices, blank=True, null=True
    )
    ment_hlth = models.IntegerField(
        _("Mental Health Days"),
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text=_("Days mental health was not good (last 30 days)."),
    )
    phys_hlth = models.IntegerField(
        _("Physical Health Days"),
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text=_("Days physical health was not good (last 30 days)."),
    )
    diff_walk = models.IntegerField(_("Difficulty Walking?"), choices=YesNo.choices, default=0)
    sex = models.CharField(
        _("Sex"),
        max_length=1,
        choices=Sex.choices,
        blank=True,
        null=True,
        help_text=_("M = Male, F = Female"),
    )

    # Age group auto-calculated from DOB
    age_group = models.IntegerField(
        _("Age Group"),
        choices=AgeGroup.choices,
        editable=False,
        blank=True,
        null=True,
    )

    education = models.IntegerField(
        _("Education Level"),
        choices=EducationLevel.choices,
        blank=True,
        null=True,
    )
    income = models.IntegerField(
        _("Income Level"),
        choices=IncomeLevel.choices,
        blank=True,
        null=True,
    )

    # --- notes & prediction ---
    past_medical_history = models.TextField(_("Past Medical History"), blank=True, null=True)
    drug_history = models.TextField(_("Drug History"), blank=True, null=True)
    investigations = models.TextField(_("Investigations"), blank=True, null=True)

    diabetes_prediction = models.IntegerField(
        _("Predicted Diabetes Status"),
        choices=DiabetesStatus.choices,
        blank=True,
        null=True,
        help_text=_("Auto-generated by AI model."),
    )
    prediction_proba = models.JSONField(
        _("Prediction Probabilities"),
        blank=True,
        null=True,
        help_text=_('e.g. {"0":0.72,"1":0.18,"2":0.10}'),
    )
    clinical_notes = models.TextField(_("Clinical Notes"), blank=True, null=True)

    # --- relations & meta ---
    doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.SET_NULL,
        related_name="patients",
        verbose_name=_("Assigned Doctor"),
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Patient")
        verbose_name_plural = _("Patients")
        ordering = ["-created_at", "full_name"]
        indexes = [
            models.Index(fields=["doctor", "full_name"]),
            models.Index(fields=["date_of_birth"]),
            models.Index(fields=["doctor", "created_at"]),
            # faster case-insensitive search by name
            models.Index(Lower("full_name"), name="idx_patient_full_name_lower"),
            # optional: case-insensitive lookup by email
            models.Index(Lower("email"), name="idx_patient_email_lower"),
        ]
        constraints = [
            # BMI range (DB-level) consistent with field validators
            models.CheckConstraint(
                check=(Q(bmi__gte=10) & Q(bmi__lte=80)) | Q(bmi__isnull=True),
                name="patient_bmi_range",
            ),
            # HbA1c range (DB-level)
            models.CheckConstraint(
                check=(Q(hbA1c__gte=3) & Q(hbA1c__lte=15)) | Q(hbA1c__isnull=True),
                name="patient_hba1c_range",
            ),
            # ment_hlth & phys_hlth ranges (DB-level)
            models.CheckConstraint(
                check=(Q(ment_hlth__gte=0) & Q(ment_hlth__lte=30)) | Q(ment_hlth__isnull=True),
                name="patient_ment_hlth_range",
            ),
            models.CheckConstraint(
                check=(Q(phys_hlth__gte=0) & Q(phys_hlth__lte=30)) | Q(phys_hl_h__isnull=True)
                if False  # safeguard: keep original name
                else (Q(phys_hlth__gte=0) & Q(phys_hlth__lte=30)) | Q(phys_hlth__isnull=True),
                name="patient_phys_hlth_range",
            ),
            # Age group valid window if present
            models.CheckConstraint(
                check=(Q(age_group__gte=1) & Q(age_group__lte=13)) | Q(age_group__isnull=True),
                name="patient_age_group_valid",
            ),
            # Uniqueness of non-empty mobile (normalized in save)
            models.UniqueConstraint(
                fields=["mobile"],
                condition=Q(mobile__gt=""),
                name="uniq_patient_mobile_nonempty",
            ),
            # Case-insensitive uniqueness for non-empty emails (PostgreSQL recommended)
            models.UniqueConstraint(
                Lower("email"),
                condition=Q(email__isnull=False) & ~Q(email=""),
                name="uniq_patient_email_lower",
            ),
        ]

    # ------------------------------------------------------------------ #
    #                               Hooks                                #
    # ------------------------------------------------------------------ #
    def clean(self):
        """Basic validations not enforced by field validators."""
        super().clean()
        # (Phone normalization is handled in save())

    def save(self, *args, **kwargs):
        """Normalize mobile/email and compute/reset age_group from DOB before save."""
        # --- normalize name ---
        if self.full_name:
            self.full_name = " ".join(self.full_name.split()).strip()

        # --- normalize email ---
        if self.email:
            self.email = self.email.strip().lower()

        # --- normalize mobile always ---
        if self.mobile:
            normalized = self.mobile.strip().replace(" ", "")
            if _HAS_PN:
                try:
                    parsed = _pn.parse(normalized, "IQ")  # default region: Iraq
                    normalized = _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
                except Exception:
                    # keep raw if parsing fails
                    pass
            self.mobile = normalized

        # --- compute/reset age_group from DOB ---
        if self.date_of_birth:
            years = _calc_age_years(self.date_of_birth)
            self.age_group = _years_to_group(years)
        else:
            self.age_group = None

        # Enforce model-level validators even if saved programmatically
        self.full_clean(exclude=None)

        super().save(*args, **kwargs)

    # ------------------------------------------------------------------ #
    #                            Properties                              #
    # ------------------------------------------------------------------ #
    @property
    def age(self) -> Optional[int]:
        """
        Exact age in years computed from date_of_birth.
        Returns None if DOB is missing.
        """
        if self.date_of_birth:
            return _calc_age_years(self.date_of_birth)
        return None

    @property
    def display_age(self) -> Optional[int]:
        """Backward-compatible alias that returns the same as .age."""
        return self.age

    def __str__(self) -> str:  # pragma: no cover
        return self.full_name


# ------------------------------------------------------------------ #
#                        Helper functions                             #
# ------------------------------------------------------------------ #
def _calc_age_years(dob: date) -> int:
    """Accurate age in years (accounts for month/day)."""
    today = date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def _years_to_group(years: int) -> int:
    """Convert exact age in years to AgeGroup code."""
    bins = [
        (24, 1), (29, 2), (34, 3), (39, 4), (44, 5), (49, 6), (54, 7),
        (59, 8), (64, 9), (69, 10), (74, 11), (79, 12),
    ]
    for limit, code in bins:
        if years <= limit:
            return code
    return 13  # 80+
