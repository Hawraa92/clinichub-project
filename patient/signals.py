# patient/signals.py
from __future__ import annotations

import logging
from typing import Optional, Set

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Patient

logger = logging.getLogger(__name__)
User = get_user_model()

# الحقول اللي إذا تغيّرت معناها لازم نعيد التنبؤ
DIABETES_INPUT_FIELDS: Set[str] = {
    "high_bp", "high_chol", "chol_check",
    "bmi", "hbA1c",
    "smoker", "stroke", "heart_disease_or_attack",
    "phys_activity", "fruits", "veggies",
    "hvy_alcohol_consump", "any_healthcare", "no_doc_bc_cost",
    "gen_hlth", "ment_hlth", "phys_hlth", "diff_walk",
    "sex", "date_of_birth", "age_group",
    "education", "income",
}

# الحقول الناتجة (حتى لو انحفظت ما نعيد التنبؤ)
PRED_OUTPUT_FIELDS: Set[str] = {"diabetes_prediction", "prediction_proba", "diabetes_status"}


def _has_enough_data_for_prediction(p: Patient) -> bool:
    """
    ما نريد نتنبأ لمريض كله فارغ.
    نعتبر كافي إذا موجود واحد على الأقل من:
    BMI أو HbA1c أو DOB/age_group أو أي عامل خطر = YES
    """
    if getattr(p, "bmi", None) is not None:
        return True
    if getattr(p, "hbA1c", None) is not None:
        return True
    if getattr(p, "date_of_birth", None) is not None:
        return True
    if getattr(p, "age_group", None) not in (None, "", 0, "0"):
        return True

    for f in ("high_bp", "high_chol", "smoker", "stroke", "heart_disease_or_attack", "diff_walk"):
        v = getattr(p, f, None)
        if v in (1, "1", True):
            return True

    # إذا الطبيب كتب general health / education / income
    for f in ("gen_hlth", "education", "income"):
        if getattr(p, f, None) not in (None, "", 0, "0"):
            return True

    return False


@receiver(post_save, sender=User)
def create_patient_profile_and_group(sender, instance, created, **kwargs):
    """
    لما ينخلق User جديد ودوره 'patient':
    1) ننشئ له Patient profile
    2) نضيفه تلقائياً إلى Group 'Patients'
    """
    if not created:
        return

    if getattr(instance, "role", None) != "patient":
        return

    Patient.objects.create(
        user=instance,
        full_name=instance.get_full_name() or instance.username
    )

    group, _ = Group.objects.get_or_create(name="Patients")
    instance.groups.add(group)


@receiver(post_save, sender=Patient)
def auto_diabetes_prediction(sender, instance: Patient, created: bool, update_fields: Optional[set] = None, **kwargs):
    """
    Auto-run ML prediction when patient medical fields change.
    """
    # إذا كان الحفظ فقط لحقول التنبؤ نفسها، لا نعيد التنبؤ
    if update_fields:
        uf = set(update_fields)
        if uf and uf.issubset(PRED_OUTPUT_FIELDS):
            return
        # إذا التعديل ما لمس أي input fields، لا نعيد التنبؤ
        if not (uf & DIABETES_INPUT_FIELDS) and not created:
            return

    if not instance.pk:
        return

    # لا نتنبأ إذا ماكو بيانات كافية
    if not _has_enough_data_for_prediction(instance):
        return

    try:
        from .services import predict_and_save
        predict_and_save(instance)
    except Exception as exc:
        logger.warning("Auto diabetes prediction failed for Patient %s: %s", instance.pk, exc)
