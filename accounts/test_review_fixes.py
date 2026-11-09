"""Regression tests for the pre-deploy review fixes (8-9 Nov 2026)."""
import datetime
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from placements.models import Application, PlacementDrive
from students.models import RecruiterProfile, StudentProfile
from students.validators import validate_resume


def make_user(username, role='student', **extra):
    return User.objects.create_user(username=username, password='Pass12345!x', role=role,
                                    email=f'{username}@example.com', **extra)


def make_drive(recruiter, **kw):
    fields = dict(posted_by=recruiter, company='Acme', role='Dev', description='d', location='Pune',
                  salary_amount=5, salary_type='lpa', job_type='full_time', eligible_branch='ALL',
                  min_cgpa=0, deadline=timezone.localdate() + datetime.timedelta(days=5))
    fields.update(kw)
    return PlacementDrive.objects.create(**fields)


class GreetingTests(TestCase):
    def test_greeting_follows_the_hour(self):
        make_user('stu')
        self.client.force_login(User.objects.get(username='stu'))
        for hour, word in ((9, 'Morning'), (14, 'Afternoon'), (20, 'Evening')):
            with mock.patch('django.template.defaulttags.datetime') as dt:
                dt.now.return_value = datetime.datetime(2026, 11, 9, hour, 0)
                html = self.client.get(reverse('dashboard')).content.decode()
            self.assertIn(f'Good {word}', html, hour)


class DriveLogicTests(TestCase):
    def setUp(self):
        self.rec = make_user('rec', 'recruiter')

    def test_branch_filter_keeps_all_branch_drives(self):
        make_drive(self.rec, role='Everyone', eligible_branch='ALL')
        make_drive(self.rec, role='CseOnly', eligible_branch='CSE')
        make_drive(self.rec, role='MechOnly', eligible_branch='ME')
        make_user('stu')
        self.client.force_login(User.objects.get(username='stu'))
        html = self.client.get(reverse('drive_list'), {'branch': 'CSE'}).content.decode()
        self.assertIn('Everyone', html)
        self.assertIn('CseOnly', html)
        self.assertNotIn('MechOnly', html)

    def test_deploy_script_does_not_close_drives_for_good(self):
        """Closing is stored permanently; extending a deadline could then never reopen a drive."""
        build = (Path(settings.BASE_DIR) / 'build.sh').read_text()
        self.assertNotIn('close_expired_drives', build)

    def test_extending_deadline_of_expired_drive_reopens_it(self):
        drive = make_drive(self.rec, deadline=timezone.localdate() - datetime.timedelta(days=1))
        self.assertFalse(PlacementDrive.objects.open().filter(pk=drive.pk).exists())
        drive.deadline = timezone.localdate() + datetime.timedelta(days=7)
        drive.save()
        self.assertTrue(PlacementDrive.objects.open().filter(pk=drive.pk).exists())


class ResumeValidatorTests(TestCase):
    def test_non_pdf_bytes_with_pdf_name_rejected(self):
        with self.assertRaises(ValidationError):
            validate_resume(SimpleUploadedFile('cv.pdf', b'<html><script>alert(1)</script>'))

    def test_real_pdf_header_accepted(self):
        validate_resume(SimpleUploadedFile('cv.pdf', b'%PDF-1.4 body'))


class StatusChangeTests(TestCase):
    def test_same_status_does_not_notify_again(self):
        rec, stu = make_user('rec', 'recruiter'), make_user('stu')
        app = Application.objects.create(student=stu, drive=make_drive(rec))
        self.client.force_login(User.objects.get(username='rec'))
        url = reverse('update_application', args=[app.pk])
        self.client.post(url, {'status': 'shortlisted'})
        self.assertEqual(Notification.objects.filter(user=stu).count(), 1)
        self.client.post(url, {'status': 'shortlisted'})  # same again
        self.assertEqual(Notification.objects.filter(user=stu).count(), 1)


class LongInputTests(TestCase):
    """Postgres rejects over-long values with a 500; these views must validate instead."""

    def test_verification_request_with_long_company_name(self):
        rec = make_user('rec', 'recruiter')
        self.client.force_login(User.objects.get(username='rec'))
        resp = self.client.post(reverse('request_verification'), {
            'company_name': 'X' * 150, 'designation': 'HR', 'industry': 'Technology'})
        self.assertEqual(resp.status_code, 200)  # form shown again, not a crash or a redirect
        profile = RecruiterProfile.objects.get(user=rec)
        self.assertNotEqual(profile.verification_status, 'pending')

    def test_verification_request_valid(self):
        rec = make_user('rec', 'recruiter')
        self.client.force_login(User.objects.get(username='rec'))
        resp = self.client.post(reverse('request_verification'), {
            'company_name': 'Acme', 'designation': 'HR', 'industry': 'Technology',
            'company_website': 'https://acme.example', 'verification_note': 'hi'})
        self.assertRedirects(resp, reverse('verification_status'))
        profile = RecruiterProfile.objects.get(user=rec)
        self.assertEqual(profile.verification_status, 'pending')
        self.assertIsNotNone(profile.verification_requested_at)

    def test_verification_request_rejects_script_url(self):
        make_user('rec', 'recruiter')
        self.client.force_login(User.objects.get(username='rec'))
        resp = self.client.post(reverse('request_verification'), {
            'company_name': 'Acme', 'designation': 'HR', 'industry': 'Technology',
            'company_website': 'javascript:alert(1)'})
        self.assertEqual(resp.status_code, 200)

    def test_admin_profile_edit_validates_phone(self):
        admin = make_user('boss', 'admin')
        self.client.force_login(User.objects.get(username='boss'))
        resp = self.client.post(reverse('edit_profile'), {
            'first_name': 'A', 'last_name': 'B', 'phone': '9' * 40})
        self.assertEqual(resp.status_code, 200)
        admin.refresh_from_db()
        self.assertNotEqual(admin.phone, '9' * 40)
        resp = self.client.post(reverse('edit_profile'), {
            'first_name': 'A', 'last_name': 'B', 'phone': '+91 98765 43210'})
        self.assertRedirects(resp, reverse('profile'))
