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


class DriveLogoValidationTests(TestCase):
    def setUp(self):
        from students.models import RecruiterProfile
        self.rec = make_user('rec', 'recruiter')
        RecruiterProfile.objects.create(user=self.rec, company_name='Acme', verification_status='approved')
        self.client.force_login(self.rec)

    def data(self, logo):
        return {
            'company': 'Acme', 'role': 'Dev', 'description': 'Build things', 'location': 'Delhi',
            'job_type': 'full_time', 'eligible_branch': PlacementDrive.BRANCH_CHOICES[0][0],
            'min_cgpa': '6', 'salary_type': 'not_disclosed', 'salary_amount': '',
            'skills_required': 'python', 'deadline': (timezone.localdate() + timedelta(days=9)).isoformat(),
            'company_logo': logo,
        }

    def test_docx_logo_is_rejected_on_post(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(reverse('post_drive'), self.data(
            SimpleUploadedFile('brief.docx', b'PK\x03\x04 fake', content_type='application/msword')))
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')
        self.assertFalse(PlacementDrive.objects.exists())

    def test_oversized_logo_is_rejected_on_post(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from students.tests import png_bytes
        big = SimpleUploadedFile('big.png', png_bytes() + b'0' * (2 * 1024 * 1024), content_type='image/png')
        resp = self.client.post(reverse('post_drive'), self.data(big))
        self.assertContains(resp, 'smaller than 2 MB')
        self.assertFalse(PlacementDrive.objects.exists())

    def test_real_logo_is_accepted(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from students.tests import png_bytes
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            resp = self.client.post(reverse('post_drive'), self.data(
                SimpleUploadedFile('logo.png', png_bytes(), content_type='image/png')))
            self.assertEqual(resp.status_code, 302)
        self.assertTrue(PlacementDrive.objects.get().company_logo)

    def test_docx_logo_is_rejected_on_edit(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        drive = PlacementDrive.objects.create(
            posted_by=self.rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.localdate() + timedelta(days=5))
        resp = self.client.post(reverse('edit_drive', args=[drive.pk]), {
            'company': 'Changed', 'company_logo': SimpleUploadedFile('x.docx', b'PK fake')})
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')
        drive.refresh_from_db()
        self.assertEqual(drive.company, 'Acme')   # nothing was saved


# ───────────────────────── Drive form (post + edit) ─────────────────────────
class DriveFormTests(TestCase):
    def setUp(self):
        from students.models import RecruiterProfile
        self.rec = make_user('rec', 'recruiter')
        RecruiterProfile.objects.create(user=self.rec, company_name='Acme', verification_status='approved')
        self.client.force_login(self.rec)
        self.drive = PlacementDrive.objects.create(
            posted_by=self.rec, company='Acme', role='Dev', description='d', location='Delhi',
            job_type='full_time', eligible_branch='CSE', min_cgpa=6.0, salary_type='lpa', salary_amount=8.0,
            deadline=timezone.localdate() + timedelta(days=5))

    def edit(self, **over):
        data = {'company': 'Acme', 'role': 'Dev', 'description': 'd', 'location': 'Delhi',
                'job_type': 'full_time', 'eligible_branch': 'CSE', 'min_cgpa': '6', 'salary_type': 'lpa',
                'salary_amount': '8', 'skills_required': 'python',
                'deadline': (timezone.localdate() + timedelta(days=5)).isoformat()}
        data.update(over)
        return self.client.post(reverse('edit_drive', args=[self.drive.pk]), data)

    def test_valid_edit_is_saved(self):
        resp = self.edit(role='Senior Dev', min_cgpa='7.5')
        self.assertRedirects(resp, reverse('recruiter_dashboard'), fetch_redirect_response=False)
        self.drive.refresh_from_db()
        self.assertEqual((self.drive.role, self.drive.min_cgpa), ('Senior Dev', 7.5))

    def test_garbage_deadline_does_not_crash_and_saves_nothing(self):
        for bad in ('not-a-date', '2026-13-45', ''):
            resp = self.edit(deadline=bad, role='Hacked')
            self.assertEqual(resp.status_code, 200, bad)
            self.assertContains(resp, 'Deadline')
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.role, 'Dev')

    def test_past_deadline_rejected_on_edit(self):
        resp = self.edit(deadline=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertContains(resp, 'The deadline cannot be in the past.')

    def test_unchanged_past_deadline_can_still_be_edited(self):
        PlacementDrive.objects.filter(pk=self.drive.pk).update(deadline=timezone.localdate() - timedelta(days=3))
        self.drive.refresh_from_db()
        resp = self.edit(deadline=self.drive.deadline.isoformat(), role='Renamed')
        self.assertEqual(resp.status_code, 302)
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.role, 'Renamed')

    def test_bad_numbers_rejected(self):
        for field, value in (('min_cgpa', 'nan'), ('min_cgpa', '11'), ('min_cgpa', '-1'), ('min_cgpa', 'abc'),
                             ('salary_amount', 'inf'), ('salary_amount', '-5'), ('salary_amount', 'abc')):
            resp = self.edit(**{field: value})
            self.assertEqual(resp.status_code, 200, (field, value))
        self.drive.refresh_from_db()
        self.assertEqual((self.drive.min_cgpa, self.drive.salary_amount), (6.0, 8.0))

    def test_invalid_choices_rejected(self):
        self.assertEqual(self.edit(job_type='astronaut').status_code, 200)
        self.assertEqual(self.edit(eligible_branch='XYZ').status_code, 200)
        self.assertEqual(self.edit(salary_type='bitcoin').status_code, 200)

    def test_blank_required_text_rejected(self):
        self.assertEqual(self.edit(company='   ').status_code, 200)
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.company, 'Acme')

    def test_not_disclosed_salary_may_be_blank(self):
        resp = self.edit(salary_type='not_disclosed', salary_amount='')
        self.assertEqual(resp.status_code, 302)
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.salary_amount, 0.0)

    def test_blank_salary_rejected_when_type_needs_one(self):
        self.assertEqual(self.edit(salary_type='lpa', salary_amount='').status_code, 200)

    def test_blank_min_cgpa_means_no_minimum(self):
        self.edit(min_cgpa='')
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.min_cgpa, 0.0)

    def test_other_recruiter_cannot_edit(self):
        other = make_user('other', 'recruiter')
        self.client.force_login(other)
        self.edit(role='Stolen')
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.role, 'Dev')

    def test_post_requires_logo_and_valid_fields(self):
        resp = self.client.post(reverse('post_drive'), {
            'company': 'New', 'role': 'R', 'description': 'd', 'location': 'L', 'job_type': 'full_time',
            'eligible_branch': 'ALL', 'min_cgpa': '0', 'salary_type': 'lpa', 'salary_amount': '5',
            'deadline': (timezone.localdate() + timedelta(days=3)).isoformat()})
        self.assertContains(resp, 'Company logo')
        self.assertEqual(PlacementDrive.objects.count(), 1)

    def test_post_with_past_deadline_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from students.tests import png_bytes
        resp = self.client.post(reverse('post_drive'), {
            'company': 'New', 'role': 'R', 'description': 'd', 'location': 'L', 'job_type': 'full_time',
            'eligible_branch': 'ALL', 'min_cgpa': '0', 'salary_type': 'lpa', 'salary_amount': '5',
            'deadline': (timezone.localdate() - timedelta(days=1)).isoformat(),
            'company_logo': SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')})
        self.assertContains(resp, 'The deadline cannot be in the past.')
        self.assertEqual(PlacementDrive.objects.count(), 1)


# ───────────────────────────── Pagination ─────────────────────────────
class PaginationTests(TestCase):
    def setUp(self):
        self.rec = make_user('rec', 'recruiter')
        self.student = make_user('stu', 'student')
        StudentProfile.objects.create(user=self.student, branch='CSE', cgpa=8.0)
        today = timezone.localdate()
        for i in range(30):
            PlacementDrive.objects.create(
                posted_by=self.rec, company=f'Company{i:02d}', role='Dev', description='d', location='X',
                job_type='full_time', deadline=today + timedelta(days=5),
                eligible_branch='CSE' if i % 2 == 0 else 'ECE')
        self.client.force_login(self.student)

    def test_first_page_has_12_of_30(self):
        resp = self.client.get(reverse('drive_list'))
        self.assertEqual(len(resp.context['drives']), 12)
        self.assertEqual(resp.context['page_obj'].paginator.num_pages, 3)
        self.assertContains(resp, 'Page 1 of 3')

    def test_every_drive_appears_exactly_once_across_pages(self):
        seen = []
        for page in (1, 2, 3):
            seen += [d.pk for d in self.client.get(reverse('drive_list'), {'page': page}).context['drives']]
        self.assertEqual(len(seen), 30)
        self.assertEqual(len(set(seen)), 30)

    def test_bad_page_numbers_do_not_crash(self):
        self.assertEqual(self.client.get(reverse('drive_list'), {'page': 'abc'}).context['page_obj'].number, 1)
        self.assertEqual(self.client.get(reverse('drive_list'), {'page': '999'}).context['page_obj'].number, 3)
        self.assertEqual(self.client.get(reverse('drive_list'), {'page': '-4'}).status_code, 200)

    def test_filters_survive_in_page_links(self):
        resp = self.client.get(reverse('drive_list'), {'branch': 'CSE'})
        self.assertEqual(resp.context['page_obj'].paginator.count, 15)
        resp = self.client.get(reverse('drive_list'), {'branch': 'CSE', 'page': 1})
        self.assertEqual(resp.context['page_obj'].paginator.num_pages, 2)
        self.assertContains(resp, 'branch=CSE&amp;page=2')

    def test_no_pagination_bar_for_short_lists(self):
        PlacementDrive.objects.filter(pk__gt=PlacementDrive.objects.order_by('pk')[4].pk).delete()
        self.assertNotContains(self.client.get(reverse('drive_list')), 'Page 1 of')

    def test_search_students_paginates_and_counts_all(self):
        from students.models import RecruiterProfile
        admin = make_user('boss', 'admin')
        for i in range(25):
            u = make_user(f's{i:02d}', 'student')
            StudentProfile.objects.create(user=u, branch='CSE', cgpa=7.0)
        self.client.force_login(admin)
        resp = self.client.get(reverse('search_students'))
        self.assertEqual(len(resp.context['students']), 12)
        self.assertContains(resp, 'Found <strong>26</strong> students')

    def test_my_applications_paginates(self):
        for d in PlacementDrive.objects.all()[:14]:
            Application.objects.create(student=self.student, drive=d)
        resp = self.client.get(reverse('my_applications'))
        self.assertEqual(len(resp.context['applications']), 10)
        self.assertContains(resp, 'Page 1 of 2')

    def test_recruiter_applicants_paginates_and_shows_true_total(self):
        drive = PlacementDrive.objects.first()
        for i in range(25):
            Application.objects.create(student=make_user(f'a{i:02d}', 'student'), drive=drive)
        self.client.force_login(drive.posted_by)
        resp = self.client.get(reverse('recruiter_applicants'), {'drive': drive.pk})
        self.assertEqual(len(resp.context['applications']), 20)
        self.assertContains(resp, '25 total applicants')


# ───────────────────── Applying requires a complete profile ─────────────────────
class ApplyNeedsCompleteProfileTests(TestCase):
    def setUp(self):
        self.rec = make_user('rec', 'recruiter')
        self.student = make_user('stu', 'student')
        self.drive = PlacementDrive.objects.create(
            posted_by=self.rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', eligible_branch='CSE', min_cgpa=7.0,
            deadline=timezone.localdate() + timedelta(days=5))
        self.client.force_login(self.student)

    def profile(self, **over):
        fields = dict(branch='CSE', cgpa=8.0, passing_year=2027, resume='resumes/x.pdf')
        fields.update(over)
        StudentProfile.objects.update_or_create(user=self.student, defaults=fields)

    def apply(self):
        return self.client.post(reverse('apply', args=[self.drive.pk]))

    def test_no_profile_at_all_is_sent_to_edit_profile(self):
        resp = self.apply()
        self.assertRedirects(resp, reverse('edit_profile'), fetch_redirect_response=False)
        self.assertFalse(Application.objects.exists())

    def test_each_missing_field_blocks_applying_and_is_named(self):
        cases = {'branch': ('', 'Branch'), 'cgpa': (0.0, 'CGPA'), 'passing_year': (None, 'Passing year'),
                 'resume': ('', 'Resume (PDF)')}
        for field, (empty, label) in cases.items():
            self.profile(**{field: empty})
            resp = self.apply()
            self.assertRedirects(resp, reverse('edit_profile'), fetch_redirect_response=False)
            self.assertFalse(Application.objects.exists(), field)
            page = self.client.get(reverse('edit_profile'))
            self.assertContains(page, f'Still needed: {label}.')

    def test_unset_branch_cannot_sneak_into_a_branch_restricted_drive(self):
        self.profile(branch='')
        self.apply()
        self.assertFalse(Application.objects.exists())

    def test_complete_profile_can_apply(self):
        self.profile()
        resp = self.apply()
        self.assertRedirects(resp, reverse('my_applications'), fetch_redirect_response=False)
        self.assertEqual(Application.objects.filter(student=self.student, drive=self.drive).count(), 1)

    def test_eligibility_still_enforced_for_complete_profiles(self):
        self.profile(cgpa=6.0)
        self.apply()
        self.assertFalse(Application.objects.exists())
        self.profile(cgpa=8.0, branch='ECE')
        self.apply()
        self.assertFalse(Application.objects.exists())

    def test_applying_twice_creates_one_application(self):
        self.profile()
        self.apply()
        self.apply()
        self.assertEqual(Application.objects.count(), 1)
