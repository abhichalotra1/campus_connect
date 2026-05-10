"""
placements/management/commands/send_deadline_reminders.py
──────────────────────────────────────────────────────────
Run this daily via cron or Windows Task Scheduler:

    python manage.py send_deadline_reminders

Cron example (Linux/Mac) — runs every day at 8 AM:
    0 8 * * * /path/to/.venv/bin/python /path/to/manage.py send_deadline_reminders

Windows Task Scheduler:
    Program: C:\\path\\to\\.venv\\Scripts\\python.exe
    Arguments: C:\\path\\to\\manage.py send_deadline_reminders
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from placements.models import PlacementDrive, Application
from accounts.models import User


class Command(BaseCommand):
    help = 'Send deadline reminder emails to eligible students 2 days before drive closes'

    def handle(self, *args, **kwargs):
        from campus_connect.email_utils import send_deadline_reminder_email

        # Find drives whose deadline is exactly 2 days from today
        target_date = timezone.now().date() + timedelta(days=2)
        drives = PlacementDrive.objects.filter(
            deadline=target_date,
            status='active'
        )

        if not drives.exists():
            self.stdout.write(self.style.WARNING(
                f'No drives closing on {target_date}. Nothing to send.'
            ))
            return

        total_sent = 0

        for drive in drives:
            # Get all eligible students who have NOT already applied
            already_applied_ids = Application.objects.filter(
                drive=drive
            ).values_list('student_id', flat=True)

            # Filter eligible students by branch and CGPA
            eligible_students = User.objects.filter(
                role='student',
                email__isnull=False
            ).exclude(
                id__in=already_applied_ids
            ).select_related('studentprofile')

            # Filter by branch eligibility
            if drive.eligible_branch != 'ALL':
                eligible_students = eligible_students.filter(
                    studentprofile__branch=drive.eligible_branch
                )

            # Filter by CGPA
            eligible_students = eligible_students.filter(
                studentprofile__cgpa__gte=drive.min_cgpa
            )

            drive_count = 0
            for student in eligible_students:
                if student.email:
                    send_deadline_reminder_email(student, drive)
                    drive_count += 1
                    total_sent += 1

            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {drive.company} – {drive.role} → {drive_count} reminders sent'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Done. Total emails sent: {total_sent}'
        ))