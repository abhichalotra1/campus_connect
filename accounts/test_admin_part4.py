from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from students.models import RecruiterProfile
from students.tests import png_bytes

PW = 'Pass12345!x'


def _user(username, role='student', **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password=PW, role=role, **extra)


class AdminRequiredTests(TestCase):
    URLS = ['admin_dashboard', 'export_students']

    def test_anonymous_goes_to_login(self):
        for name in self.URLS:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn('login', resp.url, name)

    def test_non_admins_are_turned_away(self):
        for role in ('student', 'recruiter'):
            self.client.force_login(_user(f'u_{role}', role))
            for name in self.URLS:
                self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
            for name, arg in (('admin_toggle_drive', 1), ('admin_toggle_user', 1), ('admin_verify_recruiter', 1)):
                self.assertEqual(self.client.post(reverse(name, args=[arg])).status_code, 302, name)

    def test_admin_allowed(self):
        self.client.force_login(_user('boss', 'admin'))
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('export_students')).status_code, 200)


class AdminNotificationTests(TestCase):
    def setUp(self):
        self.a1 = _user('a1', 'admin')
        self.a2 = _user('a2', 'admin')
        self.gone = _user('a3', 'admin', is_active=False)
        self.rec = _user('rec', 'recruiter')

    def test_verification_request_notifies_active_admins_only(self):
        self.client.force_login(self.rec)
        self.client.post(reverse('request_verification'), {
            'company_name': 'Acme', 'designation': 'HR', 'industry': 'Technology',
            'company_website': '', 'verification_note': ''})
        self.assertEqual(RecruiterProfile.objects.get(user=self.rec).verification_status, 'pending')
        self.assertEqual(Notification.objects.filter(title='New verification request').count(), 2)
        self.assertFalse(Notification.objects.filter(user=self.gone).exists())
        self.assertFalse(Notification.objects.filter(user=self.rec).exists())

    def test_invalid_verification_request_notifies_nobody(self):
        self.client.force_login(self.rec)
        self.client.post(reverse('request_verification'), {'company_name': ''})
        self.assertFalse(Notification.objects.exists())

    def test_recruiter_drive_notifies_admins(self):
        RecruiterProfile.objects.create(user=self.rec, company_name='Acme', verification_status='approved')
        self.client.force_login(self.rec)
        with self.settings(MEDIA_ROOT='/tmp/cc_media_test'):
            self.client.post(reverse('post_drive'), {
                'company': 'NotifyCo', 'role': 'Dev', 'description': 'd', 'location': 'L',
                'job_type': 'full_time', 'eligible_branch': 'ALL', 'min_cgpa': '0',
                'salary_type': 'not_disclosed', 'salary_amount': '',
                'deadline': (timezone.localdate() + timedelta(days=3)).isoformat(),
                'company_logo': SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')})
        self.assertEqual(Notification.objects.filter(title='New drive posted').count(), 2)

    def test_admin_posting_does_not_notify_admins(self):
        self.client.force_login(self.a1)
        with self.settings(MEDIA_ROOT='/tmp/cc_media_test'):
            self.client.post(reverse('post_drive'), {
                'company': 'Own', 'role': 'Dev', 'description': 'd', 'location': 'L',
                'job_type': 'full_time', 'eligible_branch': 'ALL', 'min_cgpa': '0',
                'salary_type': 'not_disclosed', 'salary_amount': '',
                'deadline': (timezone.localdate() + timedelta(days=3)).isoformat(),
                'company_logo': SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')})
        self.assertFalse(Notification.objects.filter(title='New drive posted').exists())


class SuperuserRoleTests(TestCase):
    def test_createsuperuser_gets_admin_role(self):
        u = User.objects.create_superuser('root', 'root@example.com', PW)
        self.assertEqual(u.role, 'admin')

    def test_promoting_existing_user_to_superuser_sets_role(self):
        u = _user('promo')
        u.is_superuser = True
        u.save()
        u.refresh_from_db()
        self.assertEqual(u.role, 'admin')

    def test_normal_users_keep_their_role(self):
        self.assertEqual(_user('s1').role, 'student')
        self.assertEqual(_user('r1', 'recruiter').role, 'recruiter')
