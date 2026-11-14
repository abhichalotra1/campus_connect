from django import forms

from placements.models import PlacementDrive
from .models import Announcement
from .services import audience_students, recruiter_daily_limit, recruiter_sent_today


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'message', 'audience', 'branch', 'drive',
                  'expires_at', 'is_pinned', 'send_email']
        widgets = {
            'title':      forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150,
                                                 'placeholder': 'e.g., Interview schedule released'}),
            'message':    forms.Textarea(attrs={'class': 'form-control', 'rows': 6, 'maxlength': 2000,
                                                'placeholder': 'Write the details students need to know...'}),
            'audience':   forms.Select(attrs={'class': 'form-select'}),
            'branch':     forms.Select(attrs={'class': 'form-select'}),
            'drive':      forms.Select(attrs={'class': 'form-select'}),
            'expires_at': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
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

        drives = PlacementDrive.objects.all() if self.is_admin else PlacementDrive.objects.filter(posted_by=user)
        self.fields['drive'].queryset = drives.order_by('-created_at')
        self.fields['drive'].required = False
        self.fields['drive'].empty_label = '— none —'
        self.fields['drive'].label_from_instance = lambda d: f'{d.company} — {d.role}'

        self.fields['branch'].choices = [('', '— choose —')] + list(self.fields['branch'].choices)[1:]
        self.fields['branch'].required = False

        if not self.is_admin:
            allowed = [c for c in Announcement.AUDIENCE_CHOICES
                       if c[0] not in Announcement.ADMIN_ONLY_AUDIENCES]
            self.fields['audience'].choices = allowed
            del self.fields['is_pinned']  # pinning is a moderation power

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
        return self.cleaned_data['title'].strip()

    def clean_message(self):
        return self.cleaned_data['message'].strip()

    def save(self, commit=True):
        announcement = super().save(commit=False)
        if announcement.audience != 'branch':
            announcement.branch = ''
        announcement.author = self.user
        return announcement
