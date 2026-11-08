from datetime import timedelta

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


def _drive(recruiter, role='Dev'):
    return PlacementDrive.objects.create(
        posted_by=recruiter, company='Acme', role=role, description='d', location='X',
        job_type='full_time', deadline=timezone.now().date() + timedelta(days=5))


class StatsPageTests(TestCase):
    def setUp(self):
        self.rec = _user('st_rec', 'recruiter')
        self.stu = _user('st_stu', 'student')
        self.stu2 = _user('st_stu2', 'student')
        for u in (self.stu, self.stu2):
            StudentProfile.objects.create(user=u, branch='CSE', cgpa=8.0)
        self.d1, self.d2 = _drive(self.rec, 'Dev'), _drive(self.rec, 'QA')

    def get(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse('stats'))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_student_numbers_and_rates(self):
        Application.objects.create(student=self.stu, drive=self.d1, status='selected')
        Application.objects.create(student=self.stu, drive=self.d2, status='shortlisted')
        resp = self.get(self.stu)
        self.assertEqual(resp.context['total_applied'], 2)
        self.assertEqual(resp.context['hero_pct'], 50)            # 1 of 2 selected
        self.assertEqual(resp.context['funnel']['forward_pct'], 100)
        self.assertContains(resp, 'st-hero')
        self.assertContains(resp, 'awaiting review')
        self.assertNotContains(resp, '{#')

    def test_student_empty_state(self):
        resp = self.get(self.stu)
        self.assertEqual(resp.context['status_total'], 0)
        self.assertContains(resp, 'Nothing to chart yet')
        self.assertNotContains(resp, 'id="statusChart"')

    def test_recruiter_sees_ranked_drives(self):
        Application.objects.create(student=self.stu, drive=self.d1)
        Application.objects.create(student=self.stu2, drive=self.d1, status='selected')
        Application.objects.create(student=self.stu, drive=self.d2)
        resp = self.get(self.rec)
        rows = resp.context['drive_rows']
        self.assertEqual([r['name'] for r in rows], ['Dev', 'QA'])
        self.assertEqual(rows[0]['pct'], 100)
        self.assertEqual(resp.context['hero_pct'], 33)             # 1 of 3 hired
        self.assertContains(resp, 'Top drives by applicants')

    def test_admin_placement_rate_counts_students_not_applications(self):
        admin = _user('st_admin', 'admin')
        # one student selected in two drives is still ONE placed student
        Application.objects.create(student=self.stu, drive=self.d1, status='selected')
        Application.objects.create(student=self.stu, drive=self.d2, status='selected')
        resp = self.get(admin)
        self.assertEqual(resp.context['selected_students'], 1)
        self.assertEqual(resp.context['hero_pct'], 50)             # 1 of 2 students
        self.assertContains(resp, 'id="branchChart"')
        self.assertContains(resp, 'id="trendChart"')

    def test_admin_with_no_applications_renders(self):
        resp = self.get(_user('st_admin2', 'admin'))
        self.assertContains(resp, 'Nothing to chart yet')
