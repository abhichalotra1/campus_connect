import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from placements.models import Application, PlacementDrive
from students.models import RecruiterProfile, StudentProfile

PW = 'Pass12345!x'


def _user(username, role='student', **extra):
    return User.objects.create_user(username=username, email=f'{username}@example.com',
                                    password=PW, role=role, **extra)


def _drive(owner, role='Dev', company='Acme', days=7, status='active'):
    return PlacementDrive.objects.create(
        posted_by=owner, company=company, role=role, description='d', location='Delhi',
        job_type='full_time', deadline=timezone.localdate() + timedelta(days=days), status=status)


class AdminPanelBase(TestCase):
    def setUp(self):
        self.admin = _user('boss', 'admin')
        self.rec = _user('rec', 'recruiter')
        RecruiterProfile.objects.create(user=self.rec, company_name='Acme', verification_status='approved')
        self.drive = _drive(self.rec)
        self.client.force_login(self.admin)

    def make_apps(self, n, prefix='s'):
        out = []
        for i in range(n):
            stu = _user(f'{prefix}{i}', first_name=f'First{i}', last_name='Last')
            StudentProfile.objects.create(user=stu, branch='CSE', cgpa=8)
            out.append(Application.objects.create(student=stu, drive=self.drive))
        return out

    def get(self, **params):
        return self.client.get(reverse('admin_dashboard'), params)


class AccessTests(AdminPanelBase):
    def test_only_admins_get_in(self):
        for who in ('rec', 'student'):
            self.client.logout()
            user = User.objects.get(username=who) if who == 'rec' else _user('stu')
            self.client.force_login(user)
            self.assertRedirects(self.get(), reverse('dashboard'), fetch_redirect_response=False)


class CountsTests(AdminPanelBase):
    def test_placed_students_counts_people_not_applications(self):
        stu = _user('twice')
        other_drive = _drive(self.rec, role='QA')
        Application.objects.create(student=stu, drive=self.drive, status='selected')
        Application.objects.create(student=stu, drive=other_drive, status='selected')
        resp = self.get()
        self.assertEqual(resp.context['placed_students'], 1)
        self.assertEqual(resp.context['counts']['applications'], 2)
        self.assertEqual(resp.context['placement_rate'], 100)   # 1 of 1 students

    def test_default_tab_is_verifications_only_when_something_is_pending(self):
        self.assertEqual(self.get().context['tab'], 'applications')
        pending = _user('newrec', 'recruiter')
        RecruiterProfile.objects.create(user=pending, verification_status='pending')
        resp = self.get()
        self.assertEqual(resp.context['tab'], 'pending')
        self.assertContains(resp, 'waiting for verification', count=0)  # banner hidden on its own tab
        self.assertEqual(self.get(tab='drives').context['counts']['pending'], 1)
        self.assertContains(self.get(tab='drives'), 'waiting for verification')


class PagingSearchTests(AdminPanelBase):
    def test_applications_are_paged(self):
        self.make_apps(40)
        self.assertEqual(len(self.get(tab='applications').context['rows']), 15)
        self.assertEqual(len(self.get(tab='applications', page=3).context['rows']), 10)
        self.assertEqual(self.get(tab='applications', page=999).status_code, 200)  # clamps, no error
        self.assertEqual(self.get(tab='applications', page='abc').status_code, 200)

    def test_search_matches_a_full_name_across_first_and_last(self):
        self.make_apps(3)
        resp = self.get(tab='applications', q='first1 last')
        self.assertEqual([a.student.username for a in resp.context['rows']], ['s1'])

    def test_search_by_company_and_status_filter(self):
        apps = self.make_apps(3)
        apps[0].status = 'shortlisted'
        apps[0].save()
        self.assertEqual(len(self.get(tab='applications', status='shortlisted').context['rows']), 1)
        self.assertEqual(len(self.get(tab='applications', q='acme').context['rows']), 3)
        self.assertEqual(len(self.get(tab='applications', q='nomatch').context['rows']), 0)

    def test_junk_parameters_are_ignored_not_fatal(self):
        resp = self.get(tab='<script>', status='hacked', state='x', q='a' * 500)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['tab'], 'applications')
        self.assertEqual(resp.context['status'], '')

    def test_drive_state_filters(self):
        _drive(self.rec, role='Old', days=-3)                 # active but past deadline
        _drive(self.rec, role='Shut', status='closed')
        roles = lambda state: sorted(d.role for d in self.get(tab='drives', state=state).context['rows'])
        self.assertEqual(roles('open'), ['Dev'])
        self.assertEqual(roles('expired'), ['Old'])
        self.assertEqual(roles('closed'), ['Shut'])
        self.assertEqual(len(roles('')), 3)

    def test_student_and_recruiter_tabs(self):
        self.make_apps(2)
        inactive = _user('gone')
        inactive.is_active = False
        inactive.save()
        self.assertEqual(len(self.get(tab='students', state='inactive').context['rows']), 1)
        self.assertEqual(len(self.get(tab='students').context['rows']), 3)
        self.assertEqual(len(self.get(tab='recruiters', state='approved').context['rows']), 1)
        self.assertEqual(len(self.get(tab='recruiters', state='rejected').context['rows']), 0)

    def test_query_count_does_not_grow_with_rows(self):
        self.make_apps(3, prefix='a')
        with CaptureQueriesContext(connection) as small:
            self.get(tab='applications')
        self.make_apps(40, prefix='b')
        with CaptureQueriesContext(connection) as big:
            self.get(tab='applications')
        self.assertEqual(len(small), len(big))
        self.assertLess(len(big), 20)


class ActionRedirectTests(AdminPanelBase):
    def test_actions_return_to_the_same_tab_and_page(self):
        target = reverse('admin_dashboard') + '?tab=drives&state=open&page=2'
        resp = self.client.post(reverse('admin_toggle_drive', args=[self.drive.pk]), {'next': target})
        self.assertRedirects(resp, target, fetch_redirect_response=False)
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.status, 'closed')

    def test_foreign_or_unrelated_next_is_ignored(self):
        for bad in ('https://evil.example/', '//evil.example', '/dashboard/', 'javascript:alert(1)'):
            resp = self.client.post(reverse('admin_toggle_drive', args=[self.drive.pk]), {'next': bad})
            self.assertRedirects(resp, reverse('admin_dashboard'), fetch_redirect_response=False)

    def test_risky_forms_ask_for_confirmation(self):
        self.make_apps(1)
        self.assertContains(self.get(tab='students'), 'data-confirm="Deactivate')
        self.assertContains(self.get(tab='drives'), 'data-confirm="Close Dev at Acme')


class VerificationDecisionTests(AdminPanelBase):
    def setUp(self):
        super().setUp()
        self.pending = _user('pend', 'recruiter')
        self.profile = RecruiterProfile.objects.create(
            user=self.pending, company_name='NewCo', verification_status='pending')

    def decide(self, **data):
        return self.client.post(reverse('admin_verify_recruiter', args=[self.pending.pk]), data)

    def test_reject_without_a_reason_is_refused(self):
        self.decide(action='reject', admin_remark='   ')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'pending')
        self.assertFalse(AuditLog.objects.filter(action='recruiter_rejected').exists())

    def test_reject_with_reason_and_approve_without_one(self):
        self.decide(action='reject', admin_remark='Website does not match')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'rejected')
        self.decide(action='approve')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'approved')

    def test_pending_card_never_links_a_non_http_website(self):
        self.profile.company_website = 'javascript:alert(1)'   # legacy row saved before validation existed
        self.profile.save()
        html = self.get(tab='pending').content.decode()
        self.assertNotIn('href="javascript:', html)
        self.profile.company_website = 'https://newco.example'
        self.profile.save()
        self.assertContains(self.get(tab='pending'), 'href="https://newco.example"')


class VerificationRequestValidationTests(TestCase):
    def setUp(self):
        self.rec = _user('reqrec', 'recruiter')
        self.profile = RecruiterProfile.objects.create(user=self.rec)
        self.client.force_login(self.rec)

    def send(self, **over):
        data = {'company_name': 'Acme', 'designation': 'HR', 'industry': 'Technology',
                'company_website': 'https://acme.example', 'verification_note': 'hi'}
        data.update(over)
        return self.client.post(reverse('request_verification'), data)

    def assert_rejected(self, resp):
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.verification_status, 'pending')

    def test_valid_request_becomes_pending(self):
        self.assertRedirects(self.send(), reverse('verification_status'), fetch_redirect_response=False)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'pending')
        self.assertIsNotNone(self.profile.verification_requested_at)

    def test_too_long_values_get_a_message_not_a_server_error(self):
        self.assert_rejected(self.send(company_name='x' * 101))
        self.assert_rejected(self.send(designation='x' * 101))
        self.assert_rejected(self.send(verification_note='x' * 1001))

    def test_bad_website_and_industry_and_missing_fields(self):
        self.assert_rejected(self.send(company_website='javascript:alert(1)'))
        self.assert_rejected(self.send(company_website='not a url'))
        self.assert_rejected(self.send(industry='Made-up'))
        self.assert_rejected(self.send(company_name=''))
        self.assert_rejected(self.send(industry=''))


class AdminProfileValidationTests(AdminPanelBase):
    def edit(self, **over):
        data = {'first_name': 'Asha', 'last_name': 'Rao', 'phone': '+91 98765 43210'}
        data.update(over)
        return self.client.post(reverse('edit_profile'), data)

    def test_valid_edit_is_saved(self):
        self.assertRedirects(self.edit(), reverse('profile'), fetch_redirect_response=False)
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.first_name, self.admin.phone), ('Asha', '+91 98765 43210'))

    def test_over_long_or_malformed_values_are_refused(self):
        for bad in ({'first_name': 'x' * 151}, {'last_name': 'x' * 151},
                    {'phone': '1' * 16}, {'phone': 'call me'}, {'first_name': ''}):
            resp = self.edit(**bad)
            self.assertEqual(resp.status_code, 200, bad)
            self.admin.refresh_from_db()
            self.assertEqual(self.admin.first_name, '', bad)


class AdminPostsDrivesTests(AdminPanelBase):
    def test_sidebar_and_header_offer_post_a_drive(self):
        html = self.get().content.decode()
        self.assertEqual(html.count(reverse('post_drive')), 2)   # sidebar + header button

    def test_admin_posts_a_drive_and_lands_on_the_drives_tab(self):
        from students.tests import png_bytes
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            resp = self.client.post(reverse('post_drive'), {
                'company': 'Walk-in Co', 'role': 'Analyst', 'description': 'd', 'location': 'Delhi',
                'job_type': 'full_time', 'eligible_branch': 'ALL', 'min_cgpa': '0',
                'salary_type': 'not_disclosed', 'salary_amount': '',
                'deadline': (timezone.localdate() + timedelta(days=5)).isoformat(),
                'company_logo': SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')})
        self.assertRedirects(resp, reverse('admin_dashboard') + '?tab=drives', fetch_redirect_response=False)
        self.assertTrue(PlacementDrive.objects.filter(company='Walk-in Co', posted_by=self.admin).exists())
