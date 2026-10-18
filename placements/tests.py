from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from placements.models import Application, Bookmark, Interview, PlacementDrive
from students.models import StudentProfile

PW = 'Pass12345!x'


def make_user(username, role):
    return User.objects.create_user(username=username, email=f'{username}@example.com', password=PW, role=role)


class PlacementSecurityTests(TestCase):
    def setUp(self):
        self.rec_a = make_user('rec_a', 'recruiter')
        self.rec_b = make_user('rec_b', 'recruiter')
        self.admin = make_user('boss', 'admin')
        self.student = make_user('stu', 'student')
        StudentProfile.objects.create(user=self.student, branch='CSE', cgpa=8.0)
        self.drive = PlacementDrive.objects.create(
            posted_by=self.rec_a, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.now().date() + timedelta(days=5))
        self.app = Application.objects.create(student=self.student, drive=self.drive)

    def login(self, username):
        self.client.logout()
        self.client.force_login(User.objects.get(username=username))

    # ── interview ownership ──
    def test_other_recruiter_cannot_schedule_interview(self):
        self.login('rec_b')
        self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                         {'scheduled_at': '2030-01-01T10:00'})
        self.assertFalse(Interview.objects.exists())

    def test_owner_can_schedule_and_is_sent_to_applicants_page(self):
        self.login('rec_a')
        resp = self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                                {'scheduled_at': '2030-01-01T10:00', 'location': 'Room 1'})
        self.assertRedirects(resp, f"{reverse('recruiter_applicants')}?drive={self.drive.pk}", fetch_redirect_response=False)
        self.assertEqual(Interview.objects.count(), 1)

    def test_admin_can_schedule_interview(self):
        self.login('boss')
        self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                         {'scheduled_at': '2030-01-01T10:00'})
        self.assertEqual(Interview.objects.count(), 1)

    def test_invalid_interview_datetime_is_rejected_without_500(self):
        self.login('rec_a')
        resp = self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                                {'scheduled_at': 'not-a-date'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Interview.objects.exists())

    def test_student_cannot_schedule(self):
        self.login('stu')
        self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                         {'scheduled_at': '2030-01-01T10:00'})
        self.assertFalse(Interview.objects.exists())

    # ── applying ──
    def test_recruiter_cannot_apply(self):
        self.login('rec_b')
        self.client.post(reverse('apply', args=[self.drive.pk]))
        self.assertFalse(Application.objects.filter(student=self.rec_b).exists())

    def test_apply_requires_post(self):
        other = make_user('stu2', 'student')
        StudentProfile.objects.create(user=other, branch='CSE', cgpa=9.0)
        self.login('stu2')
        self.assertEqual(self.client.get(reverse('apply', args=[self.drive.pk])).status_code, 405)
        self.assertFalse(Application.objects.filter(student=other).exists())

    def test_ineligible_cgpa_blocked(self):
        self.drive.min_cgpa = 9.5
        self.drive.save()
        other = make_user('stu3', 'student')
        StudentProfile.objects.create(user=other, branch='CSE', cgpa=7.0)
        self.login('stu3')
        self.client.post(reverse('apply', args=[self.drive.pk]))
        self.assertFalse(Application.objects.filter(student=other).exists())

    # ── save / unsave ──
    def test_save_and_unsave_require_post(self):
        self.login('stu')
        self.assertEqual(self.client.get(reverse('save_drive', args=[self.drive.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('unsave_drive', args=[self.drive.pk])).status_code, 405)
        self.client.post(reverse('save_drive', args=[self.drive.pk]))
        self.assertTrue(Bookmark.objects.filter(student=self.student).exists())
        self.client.post(reverse('unsave_drive', args=[self.drive.pk]))
        self.assertFalse(Bookmark.objects.exists())

    def test_unsave_ignores_external_referer(self):
        self.login('stu')
        resp = self.client.post(reverse('unsave_drive', args=[self.drive.pk]),
                                HTTP_REFERER='https://evil.example/')
        self.assertEqual(resp['Location'], reverse('saved_jobs'))

    # ── applicants page ──
    def test_admin_can_view_any_drives_applicants(self):
        self.login('boss')
        resp = self.client.get(reverse('recruiter_applicants'), {'drive': self.drive.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'stu')

    def test_recruiter_cannot_view_other_recruiters_applicants(self):
        self.login('rec_b')
        resp = self.client.get(reverse('recruiter_applicants'), {'drive': self.drive.pk})
        self.assertEqual(resp.status_code, 404)

    # ── status updates ──
    def test_other_recruiter_cannot_change_status(self):
        self.login('rec_b')
        self.client.post(reverse('update_application', args=[self.app.pk]), {'status': 'selected'})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'applied')

    def test_owner_can_change_status(self):
        self.login('rec_a')
        self.client.post(reverse('update_application', args=[self.app.pk]), {'status': 'shortlisted'})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'shortlisted')


class InterviewValidationTests(TestCase):
    def setUp(self):
        self.rec = make_user('rec', 'recruiter')
        stu = make_user('stu', 'student')
        drive = PlacementDrive.objects.create(
            posted_by=self.rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.now().date() + timedelta(days=5))
        self.app = Application.objects.create(student=stu, drive=drive)
        self.client.force_login(self.rec)

    def test_past_interview_time_rejected(self):
        resp = self.client.post(reverse('schedule_interview', args=[self.app.pk]),
                                {'scheduled_at': '2001-01-01T10:00'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Interview.objects.exists())


class RegistrationValidationTests(TestCase):
    def post(self, **over):
        data = {'username': 'newuser', 'email': 'new@example.com', 'password1': 'Str0ng!Pass-77',
                'password2': 'Str0ng!Pass-77', 'first_name': 'N', 'last_name': 'U', 'role': 'student'}
        data.update(over)
        return self.client.post(reverse('register'), data)

    def test_valid_registration(self):
        self.assertEqual(self.post().status_code, 302)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_weak_password_rejected(self):
        self.assertEqual(self.post(password1='12345678', password2='12345678').status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_duplicate_email_rejected(self):
        make_user('other', 'student')
        self.post(email='other@example.com')
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_admin_role_cannot_be_self_assigned(self):
        self.post(role='admin')
        self.assertEqual(User.objects.get(username='newuser').role, 'student')


class DriveExpiryTests(TestCase):
    def setUp(self):
        self.rec = make_user('rec', 'recruiter')
        self.student = make_user('stu', 'student')
        today = timezone.localdate()
        mk = lambda company, days, status='active': PlacementDrive.objects.create(
            posted_by=self.rec, company=company, role='Dev', description='d', location='X',
            job_type='full_time', deadline=today + timedelta(days=days), status=status)
        self.live = mk('LiveCo', 3)
        self.today = mk('TodayCo', 0)
        self.expired = mk('ExpiredCo', -1)            # still stored as 'active'
        self.closed = mk('ClosedCo', 3, status='closed')

    def test_open_queryset_excludes_expired_and_closed(self):
        names = set(PlacementDrive.objects.open().values_list('company', flat=True))
        self.assertEqual(names, {'LiveCo', 'TodayCo'})

    def test_is_open_property(self):
        self.assertTrue(self.live.is_open)
        self.assertTrue(self.today.is_open)           # deadline day itself still counts
        self.assertFalse(self.expired.is_open)
        self.assertFalse(self.closed.is_open)

    def test_drive_list_hides_expired_without_any_cleanup_job(self):
        self.client.force_login(self.student)
        resp = self.client.get(reverse('drive_list'))
        self.assertContains(resp, 'LiveCo')
        self.assertNotContains(resp, 'ExpiredCo')
        self.assertNotContains(resp, 'ClosedCo')
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.status, 'active')  # page load no longer writes to the DB

    def test_cleanup_command_closes_expired(self):
        from django.core.management import call_command
        call_command('close_expired_drives', verbosity=0)
        self.expired.refresh_from_db()
        self.live.refresh_from_db()
        self.assertEqual(self.expired.status, 'closed')
        self.assertEqual(self.live.status, 'active')
