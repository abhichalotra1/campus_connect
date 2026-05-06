from django.db import models
from accounts.models import User

class PlacementDrive(models.Model):
    JOB_TYPE_CHOICES = (
        ('full_time',  'Full Time'),
        ('internship', 'Internship'),
        ('part_time',  'Part Time'),
    )

    BRANCH_CHOICES = (
        ('ALL', 'All Branches'),
        ('CSE', 'Computer Science'),
        ('ECE', 'Electronics & Communication'),
        ('ME',  'Mechanical Engineering'),
        ('CE',  'Civil Engineering'),
        ('EE',  'Electrical Engineering'),
        ('IT',  'Information Technology'),
    )

    STATUS_CHOICES = (
        ('active', 'Active'),
        ('closed', 'Closed'),
    )

    posted_by       = models.ForeignKey(User, on_delete=models.CASCADE)
    company         = models.CharField(max_length=100)
    role            = models.CharField(max_length=100)
    description     = models.TextField()
    location        = models.CharField(max_length=100)
    package         = models.CharField(max_length=50)
    job_type        = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    eligible_branch = models.CharField(max_length=10, choices=BRANCH_CHOICES, default='ALL')
    min_cgpa        = models.FloatField(default=0.0)
    skills_required = models.TextField(blank=True)
    deadline        = models.DateField()
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company} - {self.role}"


class Application(models.Model):
    STATUS_CHOICES = (
        ('applied',     'Applied'),
        ('shortlisted', 'Shortlisted'),
        ('rejected',    'Rejected'),
        ('selected',    'Selected'),
    )

    student    = models.ForeignKey(User, on_delete=models.CASCADE)
    drive      = models.ForeignKey(PlacementDrive, on_delete=models.CASCADE)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='applied')
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'drive')

    def __str__(self):
        return f"{self.student.username} → {self.drive.company}"


class Interview(models.Model):
    STATUS_CHOICES = (
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    application  = models.OneToOneField(Application, on_delete=models.CASCADE)
    scheduled_at = models.DateTimeField()
    location     = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    notes        = models.TextField(blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.application.student.username} - {self.application.drive.company}"