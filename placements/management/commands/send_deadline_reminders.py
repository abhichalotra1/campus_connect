from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from notifications.models import Notification
from placements.models import Application, PlacementDrive
from students.models import StudentProfile


class Command(BaseCommand):
    help = (
        'Send an in-app "deadline reminder" to eligible students who have not applied '
        'to open drives closing in the next N days. Safe to run repeatedly: a student '
        'gets at most one reminder per drive.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=2,
                            help='Remind about drives whose deadline is within this many days (default 2).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show how many reminders would be sent without creating any.')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        last_day = today + timedelta(days=opts['days'])
        drives = PlacementDrive.objects.open().filter(deadline__lte=last_day)

        total = 0
        for drive in drives:
            title = f'Deadline soon: {drive.company} - {drive.role}'[:200]

            profiles = StudentProfile.objects.filter(
                user__is_active=True, user__role='student', cgpa__gte=drive.min_cgpa)
            if drive.eligible_branch != 'ALL':
                profiles = profiles.filter(branch=drive.eligible_branch)

            applied = Application.objects.filter(drive=drive).values('student_id')
            already_reminded = Notification.objects.filter(
                notif_type='deadline', title=title).values('user_id')
            user_ids = list(
                profiles.exclude(user_id__in=applied)
                        .exclude(user_id__in=already_reminded)
                        .values_list('user_id', flat=True))
            if not user_ids:
                continue

            days_left = (drive.deadline - today).days
            when = 'today' if days_left == 0 else 'tomorrow' if days_left == 1 else f'in {days_left} days'
            message = (f'Applications for {drive.role} at {drive.company} close {when} '
                       f'({drive.deadline:%d %b %Y}). Apply before the deadline.')

            total += len(user_ids)
            if not opts['dry_run']:
                Notification.objects.bulk_create([
                    Notification(user_id=uid, title=title, message=message, notif_type='deadline')
                    for uid in user_ids])

        verb = 'Would send' if opts['dry_run'] else 'Sent'
        self.stdout.write(f'{verb} {total} deadline reminder(s).')
