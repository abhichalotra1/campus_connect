from django.db import models
from django.utils import timezone

from accounts.models import User
from placements.models import PlacementDrive
from students.models import StudentProfile


class Announcement(models.Model):
    """A broadcast from an admin or verified recruiter to a group of students."""

    AUDIENCE_CHOICES = (
        ('all',         'All students'),
        ('branch',      'Students of one branch'),
        ('eligible',    'Students eligible for a drive'),
        ('applicants',  'Applicants of a drive'),
        ('shortlisted', 'Shortlisted students of a drive'),
    )
    # Audiences that only make sense together with a drive.
    DRIVE_AUDIENCES = ('eligible', 'applicants', 'shortlisted')
    # Audiences only an admin may use (they reach students the sender has no link to).
    ADMIN_ONLY_AUDIENCES = ('all', 'branch')

    author     = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='announcements')
    title      = models.CharField(max_length=150)
    message    = models.TextField(max_length=2000)
    audience   = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='applicants')
    branch     = models.CharField(max_length=10, choices=StudentProfile.BRANCH_CHOICES, blank=True)
    # Required for drive audiences; optional "related drive" link for the others.
    drive      = models.ForeignKey(PlacementDrive, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='announcements')
    is_pinned  = models.BooleanField(default=False)
    expires_at = models.DateField(null=True, blank=True, help_text='Hidden from students after this date.')
    send_email = models.BooleanField(default=False)
    recipients_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['author', '-created_at'], name='ann_author_created_idx'),
        ]

    def __str__(self):
        return f'{self.title} ({self.get_audience_display()})'

    @property
    def is_active(self):
        return self.expires_at is None or self.expires_at >= timezone.localdate()

    @property
    def author_label(self):
        """Who the students see as the sender."""
        if self.author is None:
            return 'Campus Connect'
        if self.author.role == 'admin':
            return 'Placement Cell'
        profile = getattr(self.author, 'recruiterprofile', None)
        return (profile.company_name if profile and profile.company_name else self.author.username)

    @property
    def audience_label(self):
        if self.audience == 'branch':
            return f'{self.get_branch_display()} students'
        if self.audience in self.DRIVE_AUDIENCES and self.drive:
            return f'{self.get_audience_display()} · {self.drive.company}'
        return self.get_audience_display()


class AnnouncementReceipt(models.Model):
    """One row per student an announcement was sent to: powers the student feed and the reach count."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='receipts')
    student      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcement_receipts')

    class Meta:
        unique_together = ('announcement', 'student')
        indexes = [
            models.Index(fields=['student', '-announcement'], name='ann_receipt_student_idx'),
        ]
