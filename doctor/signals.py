# doctor/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group
from .models import Doctor

@receiver(post_save, sender=Doctor)
def add_doctor_to_group(sender, instance, created, **kwargs):
    """
    لما ينخلق Doctor جديد، نضيف user مالته تلقائياً إلى Group 'Doctors'
    """
    if not created:
        return

    user = getattr(instance, "user", None)
    if user is None:
        return

    group, _ = Group.objects.get_or_create(name="Doctors")
    user.groups.add(group)
