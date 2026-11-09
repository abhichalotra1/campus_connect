from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from placements.models import Application, PlacementDrive
from students.models import StudentProfile


def student(name, branch='CSE', cgpa=8.0, active=True):
    u = User.objects.create_user(username=name, email=f'{name}@example.com', password='Pass12345!x',
                                 role='student', is_active=active)
    StudentProfile.objects.create(user=u, branch=branch, cgpa=cgpa)
    return u


class DeadlineReminderTests(TestCase):
    def setUp(self):
        self.rec = User.objects.create_user(username='rec', password='Pass12345!x', role='recruiter')
        self.today = timezone.localdate()

    def drive(self, days=1, **kw):
        defaults = dict(posted_by=self.rec, company='Acme', role='Dev', description='d', location='X',
                        job_type='full_time', deadline=self.today + timedelta(days=days))
        defaults.update(kw)
        return PlacementDrive.objects.create(**defaults)

    def run_cmd(self, *args):
        out = StringIO()
        call_command('send_deadline_reminders', *args, stdout=out)
        return out.getvalue()

    def reminded(self):
        return set(Notification.objects.filter(notif_type='deadline').values_list('user__username', flat=True))

    def test_only_eligible_unapplied_active_students_are_reminded(self):
        d = self.drive(eligible_branch='CSE', min_cgpa=7.0)
        student('ok')
        applied = student('applied'); Application.objects.create(student=applied, drive=d)
        student('wrong_branch', branch='ME')
        student('low_cgpa', cgpa=6.0)
        student('inactive', active=False)
        self.run_cmd()
        self.assertEqual(self.reminded(), {'ok'})

    def test_running_twice_does_not_duplicate(self):
        self.drive(); student('a')
        self.run_cmd(); self.run_cmd()
        self.assertEqual(Notification.objects.filter(notif_type='deadline').count(), 1)

    def test_far_expired_and_closed_drives_are_skipped(self):
        student('a')
        self.drive(days=10)
        self.drive(days=-1)
        self.drive(days=1, status='closed')
        self.run_cmd()
        self.assertEqual(self.reminded(), set())

    def test_dry_run_creates_nothing(self):
        self.drive(); student('a')
        out = self.run_cmd('--dry-run')
        self.assertIn('Would send 1', out)
        self.assertFalse(Notification.objects.exists())

    def test_days_option_widens_window(self):
        self.drive(days=5); student('a')
        self.run_cmd()
        self.assertEqual(self.reminded(), set())
        self.run_cmd('--days', '5')
        self.assertEqual(self.reminded(), {'a'})
