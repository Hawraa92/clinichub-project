from django import forms
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

from .models import PatientArchive  # Direct import is more readable

def validate_file_size(file):
    """Ensure uploaded file is not larger than 10MB"""
    limit_mb = 10
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"File '{file.name}' exceeds {limit_mb}MB limit.")

class MultiFileInput(forms.ClearableFileInput):
    """Custom widget to allow multiple file selection"""
    allow_multiple_selected = True

class MultiFileField(forms.FileField):
    """Custom field to handle multiple file uploads"""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultiFileInput(attrs={'class': 'form-control'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(d, initial) for d in data]
        elif data:
            return [single_clean(data, initial)]
        return []

class PatientArchiveForm(forms.ModelForm):
    """
    Form for creating or updating a patient archive record.
    """
    class Meta:
        model = PatientArchive
        fields = ['patient', 'doctor', 'title', 'notes', 'archive_type', 'is_critical']
        labels = {
            'patient': 'Patient',
            'doctor': 'Doctor',
            'title': 'Archive Title',
            'notes': "Doctor's Notes",
            'archive_type': 'Type',
            'is_critical': 'Is Critical',
        }
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'doctor': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'e.g., Visit Note 1, Blood Test Result'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control form-control-lg',
                'placeholder': 'Write detailed case notes here...'
            }),
            'archive_type': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'is_critical': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise forms.ValidationError("Title must be at least 5 characters.")
        return title

class ArchiveAttachmentForm(forms.Form):
    """
    Form to handle multiple file uploads with optional description.
    """
    files = MultiFileField(
        required=False,
        validators=[
            FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx']),
            validate_file_size
        ],
        help_text="Select one or more files to attach (max 10MB each)."
    )

    description = forms.CharField(
        required=False,
        label="General Description",
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'e.g., Chest X-ray, Blood Test PDF'
        })
    )

    def clean_files(self):
        files = self.cleaned_data.get('files', [])
        for file in files:
            validate_file_size(file)
        return files

    def clean(self):
        cleaned_data = super().clean()
        files = cleaned_data.get('files', [])
        description = cleaned_data.get('description', '').strip()

        if files and not description:
            raise forms.ValidationError("Please provide a description when uploading files.")

        return cleaned_data
