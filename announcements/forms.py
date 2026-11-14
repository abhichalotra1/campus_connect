from django import forms
from django.utils import timezone

from .models import Announcement
from .services import (allowed_audiences, audience_students, drives_for,
                       recruiter_daily_limit, recruiter_sent_today)

# Icon and one-line explanation shown on each audience card of the compose page.
AUDIENCE_UI = {
    'all':         ('fa-globe',        'Every active student on campus.'),
    'branch':      ('fa-code-branch',  'All students of one branch, for example CSE.'),
    'eligible':    ('fa-circle-check', 'Students who meet the drive\'s branch and CGPA rules, applied or not.'),
    'applicants':  ('fa-file-lines',   'Everyone who has applied to the drive.'),
    'shortlisted': ('fa-star',         'Applicants currently marked as shortlisted for the drive.'),
}


class NormalizedTextField(forms.CharField):
    """A CharField that counts a line break as one character.

    Browsers submit textarea line breaks as CRLF (two characters) but count them as one for
    `maxlength`, so a long multi-line message could pass in the browser and fail on the server.
    """

    def to_python(self, value):
        value = super().to_python(value)
        return value.replace('\r\n', '\n').replace('\r', '\n') if value else value


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'message', 'audience', 'branch', 'drive',
                  'expires_at', 'is_pinned', 'send_email']
        field_classes = {'message': NormalizedTextField}
        widgets = {
            'title':      forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150,
                                                 'placeholder': 'e.g., Interview schedule released',
                                                 'autocomplete': 'off'}),
            'message':    forms.Textarea(attrs={'class': 'form-control', 'rows': 7, 'maxlength': 2000,
                                                'placeholder': 'Write the details students need: what, when, where, and what to do next.'}),
            'audience':   forms.Select(attrs={'class': 'form-select'}),
            'branch':     forms.Select(attrs={'class': 'form-select'}),
            'drive':      forms.Select(attrs={'class': 'form-select'}),
            'expires_at': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'is_pinned':  forms.CheckboxInput(attrs={'data-live': 'pin'}),
            'send_email': forms.CheckboxInput(attrs={'data-live': 'email'}),
        }
        labels = {
            'audience':   'Send to',
            'branch':     'Branch',
            'drive':      'Drive',
            'expires_at': 'Hide after (optional)',
            'is_pinned':  'Pin to the top of students\' dashboards',
            'send_email': 'Also send by email',
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.is_admin = user.role == 'admin'

        self.fields['drive'].queryset = drives_for(user)
        self.fields['drive'].required = False
        self.fields['drive'].empty_label = '— none —'
        self.fields['drive'].label_from_instance = lambda d: f'{d.company} — {d.role}'

        self.fields['branch'].choices = [('', '— choose —')] + list(self.fields['branch'].choices)[1:]
        self.fields['branch'].required = False

        self.fields['expires_at'].widget.attrs['min'] = timezone.localdate().isoformat()

        allowed = allowed_audiences(user)
        self.fields['audience'].choices = [c for c in Announcement.AUDIENCE_CHOICES if c[0] in allowed]
        if not self.is_admin:
            del self.fields['is_pinned']  # pinning is a moderation power

    @property
    def audience_options(self):
        """The audiences this sender may pick, with icon/hint and which one is selected (for the cards)."""
        selected = self['audience'].value()
        options = []
        for value, label in self.fields['audience'].choices:
            icon, hint = AUDIENCE_UI.get(value, ('fa-users', ''))
            options.append({'value': value, 'label': label, 'icon': icon, 'hint': hint,
                            'checked': value == selected})
        return options

    def clean(self):
        cleaned = super().clean()
        audience = cleaned.get('audience')
        drive = cleaned.get('drive')
        branch = cleaned.get('branch') or ''

        if not self.is_admin:
            if self.instance.pk is None and recruiter_sent_today(self.user) >= recruiter_daily_limit():
                raise forms.ValidationError(
                    f'You can send up to {recruiter_daily_limit()} announcements per 24 hours. Try again later.')

        if audience == 'branch' and not branch:
            self.add_error('branch', 'Choose which branch to send to.')
        if audience in Announcement.DRIVE_AUDIENCES and drive is None:
            self.add_error('drive', 'Choose a drive for this audience.')

        if audience and not self.errors:
            recipients = audience_students(audience, branch if audience == 'branch' else '', drive).count()
            if recipients == 0:
                raise forms.ValidationError('No students match this audience, so nothing would be sent.')
        return cleaned

    def clean_title(self):
        # One line only: also collapses stray newlines/tabs that would break the email subject.
        return ' '.join(self.cleaned_data['title'].split())

    def clean_message(self):
        return self.cleaned_data['message'].strip()

    def clean_expires_at(self):
        expires_at = self.cleaned_data.get('expires_at')
        if expires_at and expires_at < timezone.localdate():
            raise forms.ValidationError('Pick today or a later date, otherwise students would never see it.')
        return expires_at

    def save(self, commit=True):
        announcement = super().save(commit=False)
        if announcement.audience != 'branch':
            announcement.branch = ''
        announcement.author = self.user
        return announcement
