# accounts/forms.py
from django import forms
from django.contrib.auth import (
    get_user_model,
    password_validation,
)
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
)
from django.utils.translation import gettext_lazy as _
from django.db import IntegrityError

User = get_user_model()


# ===================== Patient Sign Up ===================== #
class PatientSignUpForm(UserCreationForm):
    """
    Public self-registration for patients.
    Accounts created through this form are auto-approved and active immediately.
    """

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Email'),
            'autofocus': True,
            'autocomplete': 'email',
        })
    )
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Username (optional)'),
            'autocomplete': 'nickname',
        })
    )
    password1 = forms.CharField(
        label=_('Password'),
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Password'),
            'autocomplete': 'new-password',
        }),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label=_('Confirm Password'),
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Confirm Password'),
            'autocomplete': 'new-password',
        }),
        help_text=_('Enter the same password as before, for verification.'),
    )

    error_messages = {
        **UserCreationForm.error_messages,
        'duplicate_email': _('This email address is already in use.'),
        'integrity': _('We were unable to create your account. Please try again.'),
    }

    class Meta:
        model = User
        fields = ('email', 'username', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                self.error_messages['duplicate_email'],
                code='duplicate_email',
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data['email'].strip().lower()
        user.email = email

        if not user.username:
            user.username = email.split('@')[0]

        # Force patient role + approval (عدّلي إذا عندك enum / choices مختلفة)
        if hasattr(User, 'Roles') and hasattr(User.Roles, 'PATIENT'):
            user.role = User.Roles.PATIENT
        else:
            setattr(user, 'role', 'patient')

        if hasattr(user, 'is_approved'):
            user.is_approved = True

        if commit:
            try:
                user.save()
            except IntegrityError:
                raise forms.ValidationError(
                    self.error_messages['duplicate_email'],
                    code='duplicate_email',
                )
        return user


# ===================== Login (with approval check) ===================== #
class ApprovedAuthenticationForm(AuthenticationForm):
    """
    Login form (email + password) that blocks users who are not yet approved.
    We normalize the email (username field) to lowercase.
    """
    username = forms.EmailField(
        label=_('Email'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Email'),
            'autofocus': True,
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        label=_('Password'),
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Password'),
            'autocomplete': 'current-password',
        })
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'not_approved': _(
            'Your account is pending approval by an administrator. '
            'Please wait until your account is activated.'
        ),
    }

    def clean(self):
        cleaned = super().clean()
        uname = cleaned.get('username')
        if uname:
            cleaned['username'] = uname.strip().lower()
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if hasattr(user, 'is_approved') and not getattr(user, 'is_approved'):
            raise forms.ValidationError(
                self.error_messages['not_approved'],
                code='not_approved',
            )


class ExtendedApprovedAuthenticationForm(ApprovedAuthenticationForm):
    """ Placeholder for future extensions (captcha, remember me, etc.) """
    pass


# ===================== Profile Update (Settings Page) ===================== #
class ProfileUpdateForm(forms.ModelForm):
    """
    Used in secretary_settings view to update first name, last name, email.
    """
    first_name = forms.CharField(
        label=_('First name'),
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('First name'),
            'autocomplete': 'given-name',
        })
    )
    last_name = forms.CharField(
        label=_('Last name'),
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Last name'),
            'autocomplete': 'family-name',
        })
    )
    email = forms.EmailField(
        label=_('Email'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Email'),
            'autocomplete': 'email',
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError(_('Email is required.'))
        exists = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if exists.exists():
            raise forms.ValidationError(_('This email is already in use.'))
        return email


# ===================== Custom Password Change (Settings Page) ===================== #
class CustomPasswordForm(forms.Form):
    """
    Change password form matching template field names:
      - current_password
      - new_password
      - confirm_new_password
    Uses Django password validators on new_password.
    """
    current_password = forms.CharField(
        label=_('Current Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Current Password'),
            'autocomplete': 'current-password',
        })
    )
    new_password = forms.CharField(
        label=_('New Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('New Password'),
            'autocomplete': 'new-password',
        }),
        help_text=password_validation.password_validators_help_text_html()
    )
    confirm_new_password = forms.CharField(
        label=_('Confirm New Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Confirm New Password'),
            'autocomplete': 'new-password',
        })
    )

    error_messages = {
        'password_mismatch': _('The two password fields did not match.'),
        'current_incorrect': _('Your current password was entered incorrectly.'),
        'reuse_not_allowed': _('New password must be different from the current password.'),
        'confirm_without_new': _('Please enter the new password before confirming it.'),
    }

    def __init__(self, user, *args, **kwargs):
        """
        Expect the currently authenticated user to be passed explicitly:
            form = CustomPasswordForm(user=request.user, data=request.POST or None)
        """
        self.user = user
        super().__init__(*args, **kwargs)

    # تطبيع للمقارنة فقط (لا نغير القيمة الأصلية المخزّنة)
    @staticmethod
    def _normalized(val: str) -> str:
        if not val:
            return val
        # إزالة محارف صفر العرض وعلامات الاتجاه (ZWSP, ZWNJ, ZWJ, LRM, RLM, BOM)
        return val.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '') \
                  .replace('\ufeff', '').replace('\u200e', '').replace('\u200f', '')

    def clean_current_password(self):
        cur = self.cleaned_data.get('current_password')
        if not self.user.check_password(cur):
            raise forms.ValidationError(
                self.error_messages['current_incorrect'],
                code='current_incorrect'
            )
        return cur

    def clean(self):
        cleaned = super().clean()
        p_cur = cleaned.get('current_password')
        p1 = cleaned.get('new_password')
        p2 = cleaned.get('confirm_new_password')

        # تأكيد قبل كلمة جديدة
        if p2 and not p1:
            self.add_error(
                'confirm_new_password',
                self.error_messages['confirm_without_new']
            )

        # منع إعادة الاستخدام
        if p1 and p_cur and p1 == p_cur:
            self.add_error(
                'new_password',
                self.error_messages['reuse_not_allowed']
            )

        # تحقق التطابق (بعد التطبيع فقط للمقارنة)
        if p1 and p2:
            if self._normalized(p1) != self._normalized(p2):
                self.add_error(
                    'confirm_new_password',
                    self.error_messages['password_mismatch']
                )

        # إذا في أخطاء mismatch أو reuse لا نكرر رسائل validators لخفض الضجيج
        if p1 and 'new_password' not in self.errors and 'confirm_new_password' not in self.errors:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as e:
                # e.messages قائمة – Django يسمح بإضافة الكائن مباشرة
                self.add_error('new_password', e)

        return cleaned

    def save(self, commit=True):
        """
        Apply the new password to the user. View should call update_session_auth_hash.
        """
        new_pw = self.cleaned_data['new_password']
        self.user.set_password(new_pw)
        if commit:
            self.user.save()
        return self.user


