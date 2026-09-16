from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _


class LicenseActivationForm(forms.Form):
    license_token = forms.CharField(
        label=_("License token"),
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 8,
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": "CHL1.eyJ...signature",
            }
        ),
        help_text=_("Paste the complete license exactly as supplied by ClinicHub."),
    )

    def clean_license_token(self) -> str:
        token = self.cleaned_data["license_token"].strip()
        if any(character.isspace() for character in token):
            token = "".join(token.split())
        if not token.startswith("CHL1."):
            raise forms.ValidationError(_("This is not a ClinicHub CHL1 license."))
        return token
