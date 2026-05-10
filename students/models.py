from django.db import models
from accounts.models import User


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
    branch         = models.CharField(max_length=10, choices=BRANCH_CHOICES)
    cgpa           = models.FloatField(default=0.0)
    roll_number    = models.CharField(max_length=20, unique=True)
    passing_year   = models.IntegerField(default=2025)
    skills         = models.TextField(blank=True, help_text="Comma separated skills")
    certifications = models.TextField(blank=True)
    about          = models.TextField(blank=True)
    resume         = models.FileField(upload_to='resumes/', blank=True, null=True)
    profile_pic    = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    linkedin       = models.URLField(blank=True)
    github         = models.URLField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.branch}"

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
    profile_pic                = models.ImageField(upload_to='recruiter_pics/', blank=True, null=True)

    # ── Verification fields ──────────────────────────────
    is_verified                = models.BooleanField(default=False)
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