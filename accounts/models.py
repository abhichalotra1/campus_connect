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
    def __str__(self):
        return f"{self.username} ({self.role})"


class AuditLog(models.Model):
    """Append-only record of sensitive admin actions (approvals, exports, deactivations)."""
    actor      = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='audit_entries')
    action     = models.CharField(max_length=50)
    target     = models.CharField(max_length=200, blank=True)
    details    = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.actor} {self.action} {self.target}'
