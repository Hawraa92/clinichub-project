# accounts/models.py
from __future__ import annotations

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom manager using email as the unique login identifier.
    Applies default approval rules based on role, BUT respects explicit is_approved.
    """
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set"))

        # Normalize email (defense-in-depth against case-sensitive uniqueness issues)
        email = self.normalize_email(email).strip().lower()

        # Extract role (default to patient)
        role = extra_fields.pop("role", User.Roles.PATIENT)

        # Default approval rule (ONLY if caller didn't specify is_approved):
        # - patients auto-approved by default
        # - staff roles require approval by default
        # NOTE: if tests/admin pass is_approved=False explicitly, we keep it.
        extra_fields.setdefault("is_approved", True if role == User.Roles.PATIENT else False)

        user = self.model(email=email, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, role: str = "patient", **extra_fields):
        extra_fields["role"] = role
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", User.Roles.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_approved", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if extra_fields.get("role") != User.Roles.ADMIN:
            raise ValueError('Superuser must have role="admin".')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Primary authentication model.
    - Email is the login ID (unique).
    - Username is optional, non-unique, display-only (auto-filled from email if blank).
    - Role controls UI access & workflow approval.
    - assigned_doctor links each secretary to a specific doctor.
    """

    class Roles(models.TextChoices):
        DOCTOR = "doctor", _("Doctor")
        SECRETARY = "secretary", _("Secretary")
        LAB = "lab", _("Lab")
        PATIENT = "patient", _("Patient")
        ADMIN = "admin", _("Admin")

    EMAIL_FIELD = "email"

    email = models.EmailField(_("email address"), unique=True)
    username = models.CharField(
        _("username"),
        max_length=150,
        null=True,
        blank=True,
        unique=False,
        help_text=_("Auto-filled from email if left blank"),
    )

    role = models.CharField(
        _("role"),
        max_length=10,
        choices=Roles.choices,
        default=Roles.PATIENT,
        db_index=True,
        help_text=_("Determines which interface the user can access"),
    )

    is_approved = models.BooleanField(
        _("approved"),
        default=False,
        help_text=_("Must be approved by admin before logging in (for staff roles)."),
    )

    assigned_doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secretaries",
        help_text=_(
            "If this user is a secretary, link them to their primary doctor. "
            "For non-secretaries this field will be cleared automatically."
        ),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.get_full_name() or self.email

    def clean(self):
        super().clean()

        if self.email:
            self.email = self.email.strip().lower()

        if self.role != self.Roles.SECRETARY:
            self.assigned_doctor = None

    def save(self, *args, **kwargs):
        # Normalize email
        if self.email:
            self.email = self.email.strip().lower()

        # Auto-fill username from email prefix if missing
        if self.email and not self.username:
            self.username = self.email.split("@")[0]

        # ✅ Only enforce superuser approval (safe)
        if getattr(self, "is_superuser", False):
            self.is_approved = True

        # Do not force patient approval here.
        # (PatientSignUpForm / UserManager defaults handle auto-approval,
        # while tests/admin can set is_approved=False explicitly.)
        if self.role != self.Roles.SECRETARY:
            self.assigned_doctor = None

        super().save(*args, **kwargs)

    # Convenience role checks
    @property
    def is_doctor(self) -> bool:
        return self.role == self.Roles.DOCTOR

    @property
    def is_secretary(self) -> bool:
        return self.role == self.Roles.SECRETARY

    @property
    def is_lab(self) -> bool:
        return self.role == self.Roles.LAB

    @property
    def is_patient(self) -> bool:
        return self.role == self.Roles.PATIENT

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Roles.ADMIN