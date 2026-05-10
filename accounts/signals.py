"""
accounts/signals.py
────────────────────
Triggers welcome email automatically when a new user registers.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User


@receiver(post_save, sender=User)
def send_welcome_on_register(sender, instance, created, **kwargs):
    """Fire welcome email only on first creation, not on profile updates."""
    if created and instance.email:
        try:
            from campus_connect.email_utils import send_welcome_email
            send_welcome_email(instance)
        except Exception as e:
            # Never crash registration if email fails
            import logging
            logging.getLogger(__name__).error(
                f"[SIGNAL] Welcome email failed for {instance.email}: {e}"
            )