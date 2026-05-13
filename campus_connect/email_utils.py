"""
campus_connect/email_utils.py
─────────────────────────────
Drop this file at: campus_connect/email_utils.py
(same folder as settings.py and wsgi.py)

All email logic lives here. Views just call these functions.
Never raises — logs errors so the app never crashes on email failure.
"""

import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _send(subject, template, context, to_email):
    """Internal helper — renders HTML template and sends email."""
    try:
        html_body  = render_to_string(template, context)
        plain_body = strip_tags(html_body)

        msg = EmailMultiAlternatives(
            subject    = subject,
            body       = plain_body,
            from_email = settings.DEFAULT_FROM_EMAIL,
            to         = [to_email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=True)
        logger.info(f"[EMAIL] ✓ '{subject}' → {to_email}")
    except Exception as e:
        logger.error(f"[EMAIL] ✗ '{subject}' → {to_email} | Error: {e}")


# ─────────────────────────────────────────
#  1. WELCOME EMAIL  (triggered on register)
# ─────────────────────────────────────────
def send_welcome_email(user):
    """Send welcome email to newly registered user."""
    _send(
        subject  = "Welcome to Campus Connect 🎓",
        template = "emails/welcome.html",
        context  = {'user': user},
        to_email = user.email,
    )


# ─────────────────────────────────────────
#  2. APPLICATION CONFIRMATION  (student applied)
# ─────────────────────────────────────────
def send_application_email(student, drive):
    """Confirm to student that their application was received."""
    _send(
        subject  = f"Application Received – {drive.company} ({drive.role})",
        template = "emails/application_confirmation.html",
        context  = {'student': student, 'drive': drive},
        to_email = student.email,
    )


# ─────────────────────────────────────────
#  3. RECRUITER NOTIFICATION  (new applicant)
# ─────────────────────────────────────────
def send_recruiter_email(recruiter, student, drive):
    """Notify recruiter that a new student applied to their drive."""
    _send(
        subject  = f"New Application – {student.get_full_name() or student.username} applied for {drive.role}",
        template = "emails/recruiter_new_applicant.html",
        context  = {'recruiter': recruiter, 'student': student, 'drive': drive},
        to_email = recruiter.email,
    )


# ─────────────────────────────────────────
#  4. WITHDRAWAL CONFIRMATION  (student withdrew)
# ─────────────────────────────────────────
def send_withdrawal_email(student, drive):
    """Confirm to student that their application was withdrawn."""
    _send(
        subject  = f"Application Withdrawn – {drive.company}",
        template = "emails/withdrawal_confirmation.html",
        context  = {'student': student, 'drive': drive},
        to_email = student.email,
    )


# ─────────────────────────────────────────
#  5. STATUS UPDATE  (shortlisted / selected / rejected)
# ─────────────────────────────────────────
def send_status_update_email(student, drive, status):
    """
    Notify student their application status changed.
    status must be one of: 'shortlisted', 'selected', 'rejected'
    """
    subject_map = {
        'shortlisted': f"🎉 You've been Shortlisted – {drive.company}",
        'selected'   : f"🏆 Congratulations! You're Selected – {drive.company}",
        'rejected'   : f"Application Update – {drive.company}",
    }
    subject = subject_map.get(status, f"Application Update – {drive.company}")

    _send(
        subject  = subject,
        template = "emails/status_update.html",
        context  = {'student': student, 'drive': drive, 'status': status},
        to_email = student.email,
    )


# ─────────────────────────────────────────
#  6. INTERVIEW SCHEDULED
# ─────────────────────────────────────────
def send_interview_email(student, drive, scheduled_at, location='', meeting_link='', notes=''):
    """Notify student their interview has been scheduled."""
    _send(
        subject  = f"📅 Interview Scheduled – {drive.company} ({drive.role})",
        template = "emails/interview_scheduled.html",
        context  = {
            'student'      : student,
            'drive'        : drive,
            'scheduled_at' : scheduled_at,
            'location'     : location,
            'meeting_link' : meeting_link,
            'notes'        : notes,
        },
        to_email = student.email,
    )


# ─────────────────────────────────────────
#  7. DEADLINE REMINDER  (called by management command)
# ─────────────────────────────────────────
def send_deadline_reminder_email(student, drive):
    """Remind student about a drive deadline 2 days away."""
    _send(
        subject  = f"⏰ Deadline Reminder – {drive.company} closes in 2 days!",
        template = "emails/deadline_reminder.html",
        context  = {'student': student, 'drive': drive},
        to_email = student.email,
    )