# patient/signals.py

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Patient

User = get_user_model()

@receiver(post_save, sender=User)
def create_patient_profile(sender, instance, created, **kwargs):
    # إذا إنشأ مستخدم جديد ودوره 'patient'
    if created and getattr(instance, 'role', None) == 'patient':
        Patient.objects.create(
            user=instance,
            full_name=instance.get_full_name() or instance.username
        )
