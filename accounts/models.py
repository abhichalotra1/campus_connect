from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = (
        ('student', 'Student'),
        ('admin', 'Admin'),
        ('recruiter', 'Recruiter'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    phone = models.CharField(max_length=15, blank=True)
    is_verified = models.BooleanField(default=False)
    last_active_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f"{self.username} ({self.role})"
