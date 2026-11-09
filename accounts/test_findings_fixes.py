"""Regression tests for the findings-list fixes (9 Nov 2026)."""
import datetime
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from placements.models import Application, PlacementDrive


def make_user(username, role='student', **extra):
    return User.objects.create_user(username=username, password='Pass12345!x', role=role,
                                    email=f'{username}@example.com', **extra)


def make_drive(recruiter):
    return PlacementDrive.objects.create(
        posted_by=recruiter, company='Acme', role='Dev', description='d', location='Pune',
        salary_amount=5, salary_type='lpa', job_type='full_time', eligible_branch='ALL', min_cgpa=0,
        deadline=timezone.localdate() + datetime.timedelta(days=5))


def login(test, username):
    test.client.force_login(User.objects.get(username=username))


class PostOnlyActionTests(TestCase):
    def test_mark_read_needs_post(self):
        stu = make_user('stu')
        note = Notification.objects.create(user=stu, title='t', message='m')
        login(self, 'stu')
        self.assertEqual(self.client.get(reverse('mark_read', args=[note.pk])).status_code, 405)
        note.refresh_from_db()
        self.assertFalse(note.is_read)
        self.client.post(reverse('mark_read', args=[note.pk]))
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_mark_all_read_needs_post(self):
        stu = make_user('stu')
        Notification.objects.create(user=stu, title='t', message='m')
        login(self, 'stu')
        self.assertEqual(self.client.get(reverse('mark_all_read')).status_code, 405)
        self.assertEqual(Notification.objects.filter(user=stu, is_read=False).count(), 1)

    def test_notification_page_uses_a_post_form(self):
        stu = make_user('stu')
        note = Notification.objects.create(user=stu, title='t', message='m')
        login(self, 'stu')
        html = self.client.get(reverse('notifications')).content.decode()
        self.assertIn(f'action="{reverse("mark_read", args=[note.pk])}"', html)

    def test_admin_and_status_actions_reject_get(self):
        admin, rec, stu = make_user('boss', 'admin'), make_user('rec', 'recruiter'), make_user('stu')
        app = Application.objects.create(student=stu, drive=make_drive(rec))
        login(self, 'boss')
        for name, args in (('update_application', [app.pk]), ('admin_toggle_drive', [app.drive_id]),
                           ('admin_toggle_user', [stu.pk]), ('admin_verify_recruiter', [rec.pk])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 405, name)
        app.drive.refresh_from_db()
        self.assertEqual(app.drive.status, 'active')


class SessionTests(TestCase):
    def test_deactivated_user_is_logged_out_on_next_request(self):
        stu = make_user('stu')
        login(self, 'stu')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        stu.is_active = False
        stu.save()
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])


class RegistrationRaceTests(TestCase):
    def test_duplicate_username_race_is_a_message_not_a_500(self):
        data = {'username': 'newbie', 'email': 'n@example.com', 'password1': 'Str0ng!Passw0rd',
                'password2': 'Str0ng!Passw0rd', 'first_name': 'N', 'last_name': 'B',
                'phone': '', 'role': 'student'}
        with mock.patch('accounts.views.User.objects.create_user', side_effect=IntegrityError):
            resp = self.client.post(reverse('register'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'just taken')


class DriveFlowTests(TestCase):
    def test_withdraw_emails_only_after_the_delete(self):
        rec, stu = make_user('rec', 'recruiter'), make_user('stu')
        app = Application.objects.create(student=stu, drive=make_drive(rec))
        seen = {}

        def fake_email(student, drive):
            seen['still_there'] = Application.objects.filter(pk=app.pk).exists()

        login(self, 'stu')
        with mock.patch('placements.views.send_withdrawal_email', side_effect=fake_email):
            self.client.post(reverse('withdraw', args=[app.pk]))
        self.assertEqual(seen, {'still_there': False})

    def test_my_interviews_is_for_students(self):
        make_user('rec', 'recruiter')
        login(self, 'rec')
        self.assertRedirects(self.client.get(reverse('my_interviews')), reverse('dashboard'))
        make_user('stu')
        login(self, 'stu')
        self.assertEqual(self.client.get(reverse('my_interviews')).status_code, 200)

    def test_recruiter_without_profile_cannot_post_drive(self):
        make_user('rec', 'recruiter')
        login(self, 'rec')
        self.assertRedirects(self.client.get(reverse('post_drive')), reverse('verification_status'))
