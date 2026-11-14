"""Who an announcement reaches and how it is delivered. Views and tests call only these helpers."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from placements.models import Application, PlacementDrive
from .models import Announcement, AnnouncementReceipt

logger = logging.getLogger(__name__)

BATCH = 500


def active_announcements(queryset):
    """Announcements that have not passed their 'hide after' date."""
    today = timezone.localdate()
    return queryset.filter(Q(expires_at__isnull=True) | Q(expires_at__gte=today))


def allowed_audiences(user):
    """Audience values this sender may use (admins: all of them; recruiters: only drive-based ones)."""
    return [value for value, _label in Announcement.AUDIENCE_CHOICES
            if user.role == 'admin' or value not in Announcement.ADMIN_ONLY_AUDIENCES]


def drives_for(user):
    """Drives this sender may attach to an announcement: any for admins, only their own for recruiters."""
    drives = PlacementDrive.objects.all() if user.role == 'admin' else PlacementDrive.objects.filter(posted_by=user)
    return drives.order_by('-created_at')


def recruiter_daily_limit():
    return getattr(settings, 'ANNOUNCEMENT_RECRUITER_DAILY_LIMIT', 5)


def email_limit():
    return getattr(settings, 'ANNOUNCEMENT_EMAIL_LIMIT', 300)


def recruiter_sent_today(user):
    return Announcement.objects.filter(
        author=user, created_at__gte=timezone.now() - timedelta(hours=24)).count()


def audience_students(audience, branch='', drive=None):
    """Active student accounts an announcement with these settings would reach."""
    students = User.objects.filter(role='student', is_active=True)

    if audience == 'all':
        return students
    if audience == 'branch':
        return students.filter(studentprofile__branch=branch)
    if drive is None:
        return students.none()
    if audience == 'applicants':
        return students.filter(application__drive=drive).distinct()
    if audience == 'shortlisted':
        return students.filter(application__drive=drive, application__status='shortlisted').distinct()
    if audience == 'eligible':
        eligible = students.filter(studentprofile__cgpa__gte=drive.min_cgpa)
        if drive.eligible_branch != 'ALL':
            eligible = eligible.filter(studentprofile__branch=drive.eligible_branch)
        return eligible
    return students.none()


def _notification_text(announcement):
    body = announcement.message.strip()
    if len(body) > 280:
        body = body[:277].rstrip() + '...'
    return f'{body}\n— {announcement.author_label}'


def _send_email(announcement, student_ids):
    """One BCC email per batch (so addresses stay private); sent on the async backend."""
    emails = list(User.objects.filter(pk__in=student_ids).exclude(email='')
                  .values_list('email', flat=True))
    subject = f'[Campus Connect] {announcement.title}'
    body = f'{announcement.message.strip()}\n\n— {announcement.author_label}\n'
    for i in range(0, len(emails), 50):
        try:
            EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL,
                         to=[settings.DEFAULT_FROM_EMAIL], bcc=emails[i:i + 50]).send()
        except Exception:
            logger.exception('[ANNOUNCEMENT] email batch failed for announcement %s', announcement.pk)


@transaction.atomic
def publish(announcement):
    """Save the announcement and deliver it: receipts, bell notifications and (optionally) email.

    Returns (announcement, emailed) where `emailed` is False if email was requested but skipped
    because the audience is larger than ANNOUNCEMENT_EMAIL_LIMIT.
    """
    student_ids = list(audience_students(announcement.audience, announcement.branch,
                                         announcement.drive).values_list('pk', flat=True))
    announcement.recipients_count = len(student_ids)
    announcement.save()

    AnnouncementReceipt.objects.bulk_create(
        [AnnouncementReceipt(announcement=announcement, student_id=pk) for pk in student_ids],
        batch_size=BATCH)

    text = _notification_text(announcement)
    Notification.objects.bulk_create(
        [Notification(user_id=pk, title=announcement.title, message=text, notif_type='announcement')
         for pk in student_ids],
        batch_size=BATCH)

    emailed = False
    if announcement.send_email and student_ids:
        if len(student_ids) <= email_limit():
            transaction.on_commit(lambda: _send_email(announcement, student_ids))
            emailed = True
    return announcement, emailed
