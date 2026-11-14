from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import User
from django.core.exceptions import ValidationError

from .validators import validate_resume, validate_image, validate_resume_text


def default_passing_year():
    # No longer used by any field, but migration 0007 imports it by name, so it must stay.
    return timezone.now().year


class StudentProfile(models.Model):
    BRANCH_CHOICES = (
        ('CSE', 'Computer Science'),
        ('ECE', 'Electronics & Communication'),
        ('ME',  'Mechanical Engineering'),
        ('CE',  'Civil Engineering'),
        ('EE',  'Electrical Engineering'),
        ('IT',  'Information Technology'),
    )

    user           = models.OneToOneField(User, on_delete=models.CASCADE)
    # Blank until the student picks one: a silent default would make everyone look like CSE.
    branch         = models.CharField(max_length=10, choices=BRANCH_CHOICES, blank=True)
    cgpa           = models.FloatField(
                        default=0.0,
                        validators=[MinValueValidator(0), MaxValueValidator(10)],
                     )
    roll_number    = models.CharField(max_length=20, unique=True, null=True, blank=True)
    passing_year   = models.IntegerField(
                        null=True, blank=True,
                        validators=[MinValueValidator(2000), MaxValueValidator(2050)],
                     )
    skills         = models.TextField(blank=True, help_text="Comma separated skills")
    certifications = models.TextField(blank=True)
    about          = models.TextField(blank=True)
    resume         = models.FileField(upload_to='resumes/', blank=True, null=True,
                                      validators=[validate_resume])
    profile_pic    = models.ImageField(upload_to='profile_pics/', blank=True, null=True,
                                       validators=[validate_image])
    linkedin       = models.URLField(blank=True)
    github         = models.URLField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.branch}"

    # What a student must have filled in before they can apply to a drive.
    # Phone number and LinkedIn are deliberately NOT required.
    def completion_checklist(self):
        """[(label, done), ...] for the fields required to apply."""
        return [
            ('Branch', bool(self.branch)),
            ('CGPA', bool(self.cgpa and self.cgpa > 0)),
            ('Passing year', bool(self.passing_year)),
            ('Resume (PDF)', bool(self.resume)),
        ]

    def missing_required_fields(self):
        return [label for label, done in self.completion_checklist() if not done]

    @property
    def is_complete(self):
        return not self.missing_required_fields()

    def profile_completion(self):
        fields = [
            self.branch, self.cgpa, self.roll_number,
            self.skills, self.about, self.resume,
            self.linkedin, self.github
        ]
        filled = sum(1 for f in fields if f)
        return int((filled / len(fields)) * 100)


# students/models.py — only RecruiterProfile changes, StudentProfile stays same

class RecruiterProfile(models.Model):
    INDUSTRY_CHOICES = (
        ('Technology',    'Technology'),
        ('Finance',       'Finance'),
        ('Healthcare',    'Healthcare'),
        ('E-Commerce',    'E-Commerce'),
        ('Manufacturing', 'Manufacturing'),
        ('Consulting',    'Consulting'),
        ('Education',     'Education'),
        ('Media',         'Media'),
        ('Telecom',       'Telecom'),
        ('Other',         'Other'),
    )

    VERIFICATION_CHOICES = (
        ('not_requested', 'Not Requested'),
        ('pending',       'Pending'),
        ('approved',      'Approved'),
        ('rejected',      'Rejected'),
    )

    user                       = models.OneToOneField(User, on_delete=models.CASCADE)
    company_name               = models.CharField(max_length=100, blank=True)
    designation                = models.CharField(max_length=100, blank=True)
    industry                   = models.CharField(max_length=50, choices=INDUSTRY_CHOICES, blank=True)
    company_website            = models.URLField(blank=True)
    company_address            = models.TextField(blank=True)
    about                      = models.TextField(blank=True)
    linkedin                   = models.URLField(blank=True)
    profile_pic                = models.ImageField(upload_to='recruiter_pics/', blank=True, null=True,
                                                   validators=[validate_image])

    # ── Verification fields ──────────────────────────────
    verification_status        = models.CharField(
                                    max_length=20,
                                    choices=VERIFICATION_CHOICES,
                                    default='not_requested'
                                 )
    verification_note          = models.TextField(blank=True, help_text="Recruiter's message to admin")
    admin_remark               = models.TextField(blank=True, help_text="Admin's reason for approval/rejection")
    verification_requested_at  = models.DateTimeField(null=True, blank=True)
    verified_at                = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.company_name or 'Recruiter'}"

    @property
    def is_verified(self):
        """A recruiter is verified exactly when an admin has approved them."""
        return self.verification_status == 'approved'



# ── Resume Builder ───────────────────────────────────────────────────────────
# Each entry belongs to one student and has a sort position the student controls.
YEAR_VALIDATORS = [MinValueValidator(1990), MaxValueValidator(2050)]


class Education(models.Model):
    profile        = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='educations')
    institution    = models.CharField(max_length=120, validators=[validate_resume_text])
    degree         = models.CharField(max_length=100, validators=[validate_resume_text])
    field_of_study = models.CharField(max_length=100, blank=True, validators=[validate_resume_text])
    start_year     = models.PositiveSmallIntegerField(null=True, blank=True, validators=YEAR_VALIDATORS)
    end_year       = models.PositiveSmallIntegerField(null=True, blank=True, validators=YEAR_VALIDATORS)
    grade          = models.CharField(max_length=40, blank=True, validators=[validate_resume_text],
                                      help_text="For example 8.4 CGPA or 86%")
    position       = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        verbose_name_plural = 'education entries'

    def clean(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValidationError({'end_year': 'End year cannot be before the start year.'})

    def __str__(self):
        return f'{self.institution} ({self.degree})'


class Project(models.Model):
    profile     = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='projects')
    title       = models.CharField(max_length=120, validators=[validate_resume_text])
    link        = models.URLField(blank=True)
    tech        = models.CharField('Tech used', max_length=150, blank=True, validators=[validate_resume_text])
    description = models.TextField(blank=True, validators=[validate_resume_text],
                                   help_text="One bullet point per line")
    position    = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.title


class Experience(models.Model):
    profile     = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='experiences')
    company     = models.CharField(max_length=120, validators=[validate_resume_text])
    role        = models.CharField(max_length=120, validators=[validate_resume_text])
    start_date  = models.DateField()
    end_date    = models.DateField(null=True, blank=True)
    is_current  = models.BooleanField('I currently work here', default=False)
    description = models.TextField(blank=True, validators=[validate_resume_text],
                                   help_text="One bullet point per line")
    position    = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def clean(self):
        if self.is_current:
            self.end_date = None
        elif not self.end_date:
            raise ValidationError({'end_date': 'Add an end month, or tick "I currently work here".'})
        elif self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End month cannot be before the start month.'})

    def __str__(self):
        return f'{self.role} at {self.company}'


class Achievement(models.Model):
    profile  = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='achievements')
    text     = models.CharField(max_length=200, validators=[validate_resume_text])
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.text[:60]
