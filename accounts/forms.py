from django import forms

from students.models import RecruiterProfile


class VerificationRequestForm(forms.ModelForm):
    """What a recruiter sends to an admin to get verified.

    Every field is checked here so an over-long value becomes a friendly message instead of a
    database error (SQLite ignores length limits, PostgreSQL does not).
    """

    verification_note = forms.CharField(
        required=False, max_length=1000, label='Note to admin',
        widget=forms.Textarea,
    )

    class Meta:
        model = RecruiterProfile
        fields = ['company_name', 'designation', 'industry', 'company_website', 'verification_note']
        labels = {
            'company_name': 'Company name', 'designation': 'Designation',
            'industry': 'Industry', 'company_website': 'Company website',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('company_name', 'designation', 'industry'):
            self.fields[name].required = True
