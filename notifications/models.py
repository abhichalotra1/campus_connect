from django.db import models
from accounts.models import User

class Notification(models.Model):
    TYPE_CHOICES = (
        ('new_drive',    'New Drive Posted'),
        ('shortlisted',  'Shortlisted'),
        ('rejected',     'Rejected'),
        ('selected',     'Selected'),
        ('deadline',     'Deadline Reminder'),
        ('general',      'General'),
    )

    user       = models.ForeignKey(User, on_delete=models.CASCADE)
    title      = models.CharField(max_length=200)
    message    = models.TextField()
    notif_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='general')
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"