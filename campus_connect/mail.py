"""Email backend that never makes a web request wait on the mail server.

send_messages() hands the messages to a background thread and returns immediately,
so signup, apply, password reset, etc. are not held up by a slow or unreachable SMTP
server. Delivery failures are logged (there is no request left to show them to).

Threads are fine for the small volume of a campus portal on a few gunicorn workers.
If volume grows, swap this for a real queue (Celery/RQ) or an email API backend.
"""
import logging
import threading

from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend

logger = logging.getLogger(__name__)


class AsyncSMTPEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        messages = list(email_messages)
        if not messages:
            return 0
        threading.Thread(target=self._deliver, args=(messages,), daemon=True).start()
        return len(messages)

    def _deliver(self, messages):
        try:
            connection = SMTPEmailBackend(fail_silently=False)
            sent = connection.send_messages(messages)
            logger.info('[EMAIL] delivered %s of %s message(s)', sent, len(messages))
        except Exception:
            recipients = ', '.join(r for m in messages for r in m.to)
            logger.exception('[EMAIL] delivery failed for: %s', recipients)
