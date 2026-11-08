import pathlib
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from placements.models import Application, PlacementDrive
from students.models import StudentProfile

PW = 'Pass12345!x'


def _user(username, role):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password=PW, role=role)


class FormLoadingGuardTests(TestCase):
    """Every page layout must ship the loading / double-submit / wheel guard."""

    def test_public_layout_includes_guard(self):
        html = self.client.get(reverse('login')).content.decode()
        self.assertIn('id="ccBusy"', html)
        self.assertIn("a.type === 'number'", html)
        self.assertNotIn('{#', html)  # template comment must not leak into the page

    def test_dashboard_layout_includes_guard(self):
        self.client.force_login(_user('guard_stu', 'student'))
        html = self.client.get(reverse('drive_list')).content.decode()
        self.assertIn('id="ccBusy"', html)
        self.assertNotIn('{#', html)

    def test_no_template_still_calls_removed_helper(self):
        for path in pathlib.Path(settings.BASE_DIR, 'templates').rglob('*.html'):
            self.assertNotIn('submitWithLoading', path.read_text(encoding='utf-8'), str(path))


class DoubleApplyRaceTests(TestCase):
    def test_second_simultaneous_apply_is_handled_not_a_500(self):
        rec = _user('race_rec', 'recruiter')
        stu = _user('race_stu', 'student')
        StudentProfile.objects.create(user=stu, branch='CSE', cgpa=8.0)
        drive = PlacementDrive.objects.create(
            posted_by=rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.now().date() + timedelta(days=5))
        Application.objects.create(student=stu, drive=drive)  # the "other tab" won the race
        self.client.force_login(stu)

        # Make the pre-check miss it, as it would when both requests run at once.
        with mock.patch('placements.views.Application.objects.filter') as f:
            f.return_value.exists.return_value = False
            resp = self.client.post(reverse('apply', args=[drive.pk]))

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Application.objects.filter(student=stu, drive=drive).count(), 1)
