"""
accounts/signals.py
────────────────────
Triggers welcome email automatically when a new user registers.
"""

import logging
import threading

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User

logger = logging.getLogger(__name__)


def _send_welcome(user):
    try:
        from campus_connect.email_utils import send_welcome_email
        send_welcome_email(user)
    except Exception as e:
        # Never crash registration if email fails
        logger.error(f"[SIGNAL] Welcome email failed for {user.email}: {e}")


@receiver(post_save, sender=User)
def send_welcome_on_register(sender, instance, created, **kwargs):
    """Fire welcome email only on first creation, not on profile updates."""
    if created and instance.email:
        # Run after the DB commit, off the request thread, so signup never waits on SMTP
        transaction.on_commit(
            lambda: threading.Thread(target=_send_welcome, args=(instance,), daemon=True).start()
        )