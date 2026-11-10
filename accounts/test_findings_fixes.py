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


class RegistrationRoleAndPasswordToggleTests(TestCase):
    def post(self, **over):
        data = {'username': 'newbie2', 'email': 'n2@example.com', 'password1': 'Str0ng!Passw0rd',
                'password2': 'Str0ng!Passw0rd', 'first_name': 'N', 'last_name': 'B', 'phone': ''}
        data.update(over)
        return self.client.post(reverse('register'), data)

    def test_missing_role_is_rejected_not_defaulted_to_student(self):
        resp = self.post()  # no role field at all
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Student or a Recruiter')
        self.assertFalse(User.objects.filter(username='newbie2').exists())

    def test_invalid_role_is_rejected(self):
        self.assertEqual(self.post(role='admin').status_code, 200)
        self.assertFalse(User.objects.filter(username='newbie2').exists())

    def test_recruiter_role_is_kept(self):
        self.assertEqual(self.post(role='recruiter').status_code, 302)
        self.assertEqual(User.objects.get(username='newbie2').role, 'recruiter')

    def test_form_shows_both_roles_unselected_by_default(self):
        html = self.client.get(reverse('register')).content.decode()
        self.assertIn('value="student"', html)
        self.assertIn('value="recruiter"', html)
        self.assertNotIn('<select name="role"', html)
        self.assertNotIn('required checked', html)  # no radio is pre-selected

    def test_chosen_role_is_kept_after_an_error(self):
        resp = self.post(role='recruiter', password2='different')
        self.assertContains(resp, 'value="recruiter" required checked')

    def test_password_toggle_script_is_on_login_and_register(self):
        for name in ('login', 'register'):
            self.assertContains(self.client.get(reverse(name)), 'cc-pw-btn')
