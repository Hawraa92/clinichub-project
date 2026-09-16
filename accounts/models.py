from __future__ import annotations

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom manager using email as the unique login identifier.
    Applies default approval rules based on role.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Create and save a user with the supplied email and password.
        """
        if not email:
            raise ValueError(_("The Email field must be set"))

        email = self.normalize_email(email).strip().lower()
        role = extra_fields.pop("role", "patient")

        # Patients are approved automatically. Staff accounts require approval.
        extra_fields.setdefault("is_approved", role == "patient")

        user = self.model(email=email, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, role="patient", **extra_fields):
        """
        Create a regular user. The default role is patient.
        """
        extra_fields["role"] = role
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create a platform administrator with full privileges.
        """
        extra_fields.setdefault("role", "admin")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_approved", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if extra_fields.get("role") != "admin":
            raise ValueError('Superuser must have role="admin".')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Primary authentication model.

    Email is the unique login identifier. Username is optional and is used
    only for display. Role controls interface access and staff approval.
    """

    email = models.EmailField(
        _("email address"),
        unique=True,
        db_index=True,
    )

    username = models.CharField(
        _("username"),
        max_length=150,
        null=True,
        blank=True,
        unique=False,
        help_text=_("Auto-filled from email if left blank"),
    )

    class Roles(models.TextChoices):
        DOCTOR = "doctor", _("Doctor")
        SECRETARY = "secretary", _("Secretary")
        LAB = "lab", _("Lab")
        PHARMACIST = "pharmacist", _("Pharmacist")
        PATIENT = "patient", _("Patient")
        ADMIN = "admin", _("Admin")

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
        help_text=_("Must be approved by admin before logging in for staff roles."),
    )

    assigned_doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secretaries",
        help_text=_(
            "If this user is a secretary, link them to their primary doctor. "
            "For non-secretaries this field is cleared automatically."
        ),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.get_full_name() or self.email

    def clean(self):
        """
        Normalize the email and keep doctor assignment limited to secretaries.
        """
        super().clean()

        if self.email:
            self.email = self.email.strip().lower()

        if self.role != self.Roles.SECRETARY:
            self.assigned_doctor = None

    def save(self, *args, **kwargs):
        if self.email and not self.username:
            self.username = self.email.split("@")[0]

        if self.email:
            self.email = self.email.strip().lower()

        super().save(*args, **kwargs)

    @property
    def is_doctor(self):
        return self.role == self.Roles.DOCTOR

    @property
    def is_secretary(self):
        return self.role == self.Roles.SECRETARY

    @property
    def is_lab(self):
        return self.role == self.Roles.LAB

    @property
    def is_pharmacist(self):
        return self.role == self.Roles.PHARMACIST

    @property
    def is_patient(self):
        return self.role == self.Roles.PATIENT

    @property
    def is_admin_role(self):
        return self.role == self.Roles.ADMIN
