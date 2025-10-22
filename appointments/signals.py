# appointments/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Appointment
from notifications.models import Notification

@receiver(post_save, sender=Appointment)
def appointment_notification(sender, instance: Appointment, created, **kwargs):
    """
    نُشعِر السكرتير فقط عند إنشاء حجز بواسطة المريض.
    لا إشعار عند إنشاء السكرتير ولا عند تغيّر الحالة (Next Call).
    """
    # إيقاف قسري لو رُفع هذا الفلاغ من أي مكان
    if getattr(instance, "_suppress_notifications", False):
        return

    # إشعار فقط عند الإنشاء ومن مصدر "patient"
    if created and getattr(instance, "_source", None) == "patient":
        Notification.objects.create(
            recipient_role="secretary",
            event="patient_booking_created",
            appointment=instance,
            is_read=False,
        )
