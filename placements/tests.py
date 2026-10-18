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
        self.assertRedirects(resp, reverse('recruiter_applicants'), fetch_redirect_response=False)
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
