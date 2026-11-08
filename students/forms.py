from django import forms
from django.core.validators import RegexValidator

from accounts.models import User
from .models import RecruiterProfile, StudentProfile

IMAGE_MESSAGE = 'Image must be a JPG, PNG, GIF or WebP file.'

PHONE_VALIDATOR = RegexValidator(
    r'^[+0-9][0-9 ()\-]{6,14}$',
    'Enter a valid phone number (7 to 15 characters: digits, spaces, +, - and brackets).',
)


class StudentProfileForm(forms.ModelForm):
    """Academic details, links and uploads.

    Branch, CGPA and passing year are required to save (they decide which drives a student
    can apply to). Resume is checked when applying, not when saving, so a student can fill in
    the rest first. Phone number and LinkedIn stay optional.
    """

    class Meta:
        model = StudentProfile
        fields = [
            'branch', 'cgpa', 'roll_number', 'passing_year', 'skills', 'certifications',
            'about', 'resume', 'profile_pic', 'linkedin', 'github',
        ]
        labels = {
            'cgpa': 'CGPA', 'passing_year': 'Passing year', 'roll_number': 'Roll number',
            'profile_pic': 'Profile picture', 'linkedin': 'LinkedIn', 'github': 'GitHub',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('branch', 'cgpa', 'passing_year'):
            self.fields[name].required = True
        self.fields['profile_pic'].error_messages['invalid_image'] = IMAGE_MESSAGE

    def clean_cgpa(self):
        value = self.cleaned_data['cgpa']
        if not 0 < value <= 10:
            raise forms.ValidationError('Enter your CGPA as a number between 0.01 and 10.')
        return value


class UserNameForm(forms.ModelForm):
    """The name and phone fields shown at the top of the student profile page."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone']
        labels = {'first_name': 'First name', 'last_name': 'Last name', 'phone': 'Phone number'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['phone'].validators.append(PHONE_VALIDATOR)


class RecruiterProfileForm(forms.ModelForm):
    class Meta:
        model = RecruiterProfile
        fields = [
            'company_name', 'industry', 'designation', 'company_website',
            'company_address', 'about', 'linkedin', 'profile_pic',
        ]
        labels = {
            'company_name': 'Company name', 'company_website': 'Company website',
            'company_address': 'Company address', 'profile_pic': 'Profile picture',
            'linkedin': 'LinkedIn',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profile_pic'].error_messages['invalid_image'] = IMAGE_MESSAGE
