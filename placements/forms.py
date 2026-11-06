from django import forms
from django.utils import timezone

from .models import PlacementDrive


class PlacementDriveForm(forms.ModelForm):
    """One validation path for posting and editing a drive.

    Replaces the hand-written checks in the post view and the unchecked assignments in the
    edit view (which could crash on a bad date). The templates still draw their own inputs;
    this form only cleans and validates what was submitted.
    """

    class Meta:
        model = PlacementDrive
        fields = [
            'company', 'role', 'description', 'location', 'company_logo',
            'salary_type', 'salary_amount', 'job_type', 'eligible_branch',
            'min_cgpa', 'skills_required', 'deadline',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A logo is compulsory for a new drive; when editing, leaving it alone is fine.
        self.fields['company_logo'].required = not self.instance.pk
        self.fields['company_logo'].error_messages['invalid_image'] = 'Image must be a JPG, PNG, GIF or WebP file.'
        self.fields['min_cgpa'].required = False       # blank means "no minimum"
        self.fields['salary_amount'].required = False  # checked together with salary_type below
        self.fields['skills_required'].required = False

    def clean_min_cgpa(self):
        value = self.cleaned_data.get('min_cgpa')
        if value is None:
            return 0.0
        if not 0 <= value <= 10:
            raise forms.ValidationError('Minimum CGPA must be a number between 0 and 10.')
        return value

    def clean_deadline(self):
        deadline = self.cleaned_data['deadline']
        unchanged = bool(self.instance.pk) and deadline == self.instance.deadline
        if deadline < timezone.localdate() and not unchanged:
            raise forms.ValidationError('The deadline cannot be in the past.')
        return deadline

    def clean(self):
        cleaned = super().clean()
        salary = cleaned.get('salary_amount')
        salary_type = cleaned.get('salary_type')
        if salary is None:
            if salary_type == 'not_disclosed':
                cleaned['salary_amount'] = 0.0  # keeps formatted_salary showing "Not Disclosed"
            elif 'salary_type' in cleaned and 'salary_amount' not in self.errors:
                self.add_error('salary_amount', 'Enter a valid salary amount (0 or more).')
        elif salary < 0:
            self.add_error('salary_amount', 'Enter a valid salary amount (0 or more).')
        return cleaned
