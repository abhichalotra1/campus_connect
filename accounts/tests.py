from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AuditLog, User
from students.models import StudentProfile


def make_user(username, role='student', password='Pass12345!x', **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com',
        password=password, role=role, **extra,
    )


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user('alice')

    def test_missing_fields_do_not_crash(self):
        resp = self.client.post(reverse('login'), {})
        self.assertEqual(resp.status_code, 200)

    def test_login_success_redirects_to_dashboard(self):
        resp = self.client.post(reverse('login'), {'username': 'alice', 'password': 'Pass12345!x'})
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)

    def test_next_param_same_site_is_followed(self):
        resp = self.client.post(reverse('login'), {
            'username': 'alice', 'password': 'Pass12345!x', 'next': '/placements/saved-jobs/'})
        self.assertEqual(resp['Location'], '/placements/saved-jobs/')

    def test_next_param_external_is_ignored(self):
        for bad in ('https://evil.example/', '//evil.example/', 'javascript:alert(1)'):
            self.client.logout()
            resp = self.client.post(reverse('login'), {
                'username': 'alice', 'password': 'Pass12345!x', 'next': bad})
            self.assertEqual(resp['Location'], reverse('dashboard'), bad)

    def test_lockout_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'alice', 'password': 'wrong'})
        # Even the correct password is refused while locked out
        resp = self.client.post(reverse('login'), {'username': 'alice', 'password': 'Pass12345!x'})
        self.assertEqual(resp.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)


class LogoutTests(TestCase):
    def setUp(self):
        make_user('bob')
        self.client.force_login(User.objects.get(username='bob'))

    def test_get_logout_not_allowed(self):
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

    def test_post_logout_works(self):
        resp = self.client.post(reverse('logout'))
        self.assertRedirects(resp, reverse('landing'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class AdminAuditTests(TestCase):
    def setUp(self):
        self.admin = make_user('boss', role='admin')
        self.recruiter = make_user('rec', role='recruiter')
        self.student = make_user('stu')
        StudentProfile.objects.create(user=self.student, branch='CSE', skills='=HYPERLINK("http://x")')

    def test_csv_export_forbidden_for_non_admin(self):
        self.client.force_login(User.objects.get(username='stu'))
        resp = self.client.get(reverse('export_students'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AuditLog.objects.exists())

    def test_csv_export_is_logged_and_formulas_neutralised(self):
        self.client.force_login(User.objects.get(username='boss'))
        resp = self.client.get(reverse('export_students'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("'=HYPERLINK", body)
        self.assertTrue(AuditLog.objects.filter(action='export_students_csv', actor=self.admin).exists())

    def test_recruiter_approval_is_logged(self):
        self.client.force_login(User.objects.get(username='boss'))
        self.client.post(reverse('admin_verify_recruiter', args=[self.recruiter.pk]),
                         {'action': 'approve', 'admin_remark': 'ok'})
        self.recruiter.refresh_from_db()
        self.assertTrue(self.recruiter.is_verified)
        self.assertTrue(AuditLog.objects.filter(action='recruiter_approved', target='rec').exists())

    def test_non_admin_cannot_approve(self):
        self.client.force_login(User.objects.get(username='rec'))
        self.client.post(reverse('admin_verify_recruiter', args=[self.recruiter.pk]), {'action': 'approve'})
        self.recruiter.refresh_from_db()
        self.assertFalse(self.recruiter.is_verified)
