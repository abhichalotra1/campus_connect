from django.db import models
from accounts.models import User

class Notification(models.Model):
    TYPE_CHOICES = (
        ('new_drive',    'New Drive Posted'),
        ('shortlisted',  'Shortlisted'),
        ('rejected',     'Rejected'),
        ('selected',     'Selected'),
        ('deadline',     'Deadline Reminder'),
        ('announcement', 'Announcement'),
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
        indexes = [
            # unread badge / mark-all-read
            models.Index(fields=['user', 'is_read'], name='notif_user_read_idx'),
            # a user's list, newest first
            models.Index(fields=['user', '-created_at'], name='notif_user_created_idx'),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.title}"