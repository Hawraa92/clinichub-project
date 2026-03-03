# core/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """
    QuerySet يدعم:
    - delete() = soft delete افتراضياً
    - delete(hard=True) = hard delete
    - hard_delete()
    - restore()
    """

    def delete(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        hard = bool(kwargs.pop("hard", False))

        if hard:
            # يرجّع نفس tuple مال Django: (count, per_model_dict)
            return super().delete(*args, **kwargs)

        updated = super().update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=user if user and getattr(user, "is_authenticated", False) else None,
        )
        # نحاكي رجعة Django delete() حتى ما ينكسر أي كود يتوقع tuple
        return (updated, {self.model._meta.label: updated})

    def hard_delete(self):
        return super().delete()

    def restore(self):
        updated = super().update(is_deleted=False, deleted_at=None, deleted_by=None)
        return updated


class SoftDeleteManager(models.Manager):
    """Default manager: يخفي المحذوفات."""
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """Base manager: يشوف الكل (حتى المحذوف soft) لتجنب كسر العلاقات."""
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class DeletedObjectsManager(models.Manager):
    """Manager للعرض/التقارير على المحذوفات فقط."""
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted_by",
    )

    # ✅ default manager: يخفي المحذوفات
    objects = SoftDeleteManager()
    # ✅ base manager: لازم يشوف الكل (حتى العلاقات FK ما تنكسر)
    all_objects = AllObjectsManager()
    deleted_objects = DeletedObjectsManager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"      # العلاقات/ForeignKey تشوف حتى المحذوف soft
        default_manager_name = "objects"       # الاستعلامات العادية تبقى تخفي المحذوف

    def delete(self, using=None, keep_parents=False, user=None, hard=False):
        """
        Model.delete() في Django يرجّع (count, per_model_dict)
        فنحافظ على نفس السلوك حتى ما ينكسر أي كود.
        """
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user if user and getattr(user, "is_authenticated", False) else None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

        return (1, {self._meta.label: 1})

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
        return 1