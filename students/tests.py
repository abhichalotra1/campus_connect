import json
import os
import tempfile
from unittest import mock

import cloudinary
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from campus_connect.storage import CloudinaryMediaStorage
from students.models import RecruiterProfile, StudentProfile

PW = 'Pass12345!x'
CLOUD_STORAGES = {
    'default': {'BACKEND': 'campus_connect.storage.CloudinaryMediaStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def make_user(username, role):
    return User.objects.create_user(username=username, email=f'{username}@example.com', password=PW, role=role)


def profile_data(**extra):
    """A complete, valid student-profile form submission; override or add fields per test."""
    data = {'first_name': 'Stu', 'branch': 'CSE', 'cgpa': '8.0', 'passing_year': '2027'}
    data.update(extra)
    return data


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, payload):
        self.data = json.dumps(payload).encode()


class CloudinaryStorageTests(SimpleTestCase):
    def setUp(self):
        self.storage = CloudinaryMediaStorage()
        self._old = cloudinary.config().__dict__.copy()
        cloudinary.config(cloud_name='democloud', api_key='key123', api_secret='secret456')

    def tearDown(self):
        cloudinary.config().__dict__.clear()
        cloudinary.config().__dict__.update(self._old)

    def test_resume_uploaded_as_private_raw_with_random_name(self):
        # Cloudinary echoes the public_id it was given; emulate that
        holder = {}

        def fake_request(method, url, fields=None, headers=None, **kw):
            f = dict((k, v) for k, v in fields if k != 'file')
            holder.update(url=url, fields=f, has_file=any(k == 'file' for k, _ in fields))
            return FakeResponse({'public_id': f['public_id'], 'format': 'pdf', 'resource_type': 'raw',
                                 'version': 1, 'type': 'upload', 'signature': 'x'})

        with mock.patch('cloudinary.uploader._http.request', fake_request):
            saved = self.storage.save('resumes/My CV.pdf', SimpleUploadedFile('My CV.pdf', b'%PDF-1.4 x'))
        self.assertTrue(holder['url'].endswith('/democloud/raw/upload'))
        self.assertTrue(holder['has_file'])
        self.assertIn('signature', holder['fields'])           # request is signed with the API secret
        self.assertNotIn('secret456', json.dumps(holder['fields']))
        self.assertRegex(saved, r'^resumes/[0-9a-f]{32}\.pdf$')  # random, original name discarded
        self.assertNotIn('My CV', saved)

    def test_image_uploaded_as_image_and_name_uses_returned_format(self):
        holder = {}

        def fake_request(method, url, fields=None, headers=None, **kw):
            f = dict((k, v) for k, v in fields if k != 'file')
            holder.update(url=url, fields=f)
            return FakeResponse({'public_id': f['public_id'], 'format': 'jpg', 'resource_type': 'image',
                                 'version': 1, 'type': 'upload', 'signature': 'x'})

        with mock.patch('cloudinary.uploader._http.request', fake_request):
            saved = self.storage.save('profile_pics/me.jpeg', SimpleUploadedFile('me.jpeg', b'\xff\xd8\xff'))
        self.assertTrue(holder['url'].endswith('/democloud/image/upload'))
        self.assertNotIn('.jpeg', holder['fields']['public_id'])  # images: public_id has no extension
        self.assertRegex(saved, r'^profile_pics/[0-9a-f]{32}\.jpg$')

    def test_image_url_is_public_https_cloudinary_link(self):
        url = self.storage.url('company_logos/abc.png')
        self.assertEqual(url, 'https://res.cloudinary.com/democloud/image/upload/v1/company_logos/abc.png')

    def test_resume_url_goes_through_permission_view_not_cloudinary(self):
        url = self.storage.url('resumes/abc.pdf')
        self.assertEqual(url, '/students/resume/resumes/abc.pdf')
        self.assertNotIn('cloudinary', url)

    def test_cloud_url_for_resume_is_raw_asset(self):
        self.assertEqual(self.storage.cloud_url('resumes/abc.pdf'),
                         'https://res.cloudinary.com/democloud/raw/upload/v1/resumes/abc.pdf')

    def test_windows_style_backslash_names_are_handled(self):
        """Django on Windows builds 'resumes\\cv.pdf'; it must still be a private raw upload."""
        name = self.storage.generate_filename('resumes\\My CV.pdf')
        self.assertEqual(name, 'resumes/My_CV.pdf')
        self.assertTrue(self.storage.is_private('resumes\\x.pdf'))
        self.assertRegex(self.storage.get_available_name('resumes\\x.pdf'), r'^resumes/[0-9a-f]{32}\.pdf$')
        self.assertEqual(self.storage.url('company_logos\\a.png'),
                         'https://res.cloudinary.com/democloud/image/upload/v1/company_logos/a.png')
        self.assertEqual(self.storage.url('resumes\\a.pdf'), '/students/resume/resumes/a.pdf')

    def test_windows_style_upload_goes_to_raw_endpoint(self):
        holder = {}

        def fake_request(method, url, fields=None, headers=None, **kw):
            f = dict((k, v) for k, v in fields if k != 'file')
            holder.update(url=url, public_id=f['public_id'])
            return FakeResponse({'public_id': f['public_id'], 'format': 'pdf', 'version': 1,
                                 'resource_type': 'raw', 'type': 'upload', 'signature': 'x'})

        with mock.patch('cloudinary.uploader._http.request', fake_request):
            saved = self.storage.save(self.storage.generate_filename('resumes\\cv.pdf'),
                                      SimpleUploadedFile('cv.pdf', b'%PDF-1.4 x'))
        self.assertTrue(holder['url'].endswith('/raw/upload'))
        self.assertRegex(saved, r'^resumes/[0-9a-f]{32}\.pdf$')

    def test_exists_is_false_so_names_are_never_reused(self):
        self.assertFalse(self.storage.exists('resumes/abc.pdf'))

    def test_delete_failure_is_logged_not_raised(self):
        with mock.patch('cloudinary.uploader.destroy', side_effect=RuntimeError('boom')):
            with self.assertLogs('campus_connect.storage', level='ERROR'):
                self.storage.delete('resumes/abc.pdf')


@override_settings(STORAGES=CLOUD_STORAGES)
class ResumeAccessTests(TestCase):
    def setUp(self):
        cloudinary.config(cloud_name='democloud', api_key='k', api_secret='s')
        self.owner = make_user('owner', 'student')
        self.profile = StudentProfile.objects.create(user=self.owner, branch='CSE')
        StudentProfile.objects.filter(pk=self.profile.pk).update(resume='resumes/abc123.pdf')
        self.url = reverse('resume_download', kwargs={'name': 'resumes/abc123.pdf'})
        self.other = make_user('other', 'student')
        self.admin = make_user('boss', 'admin')
        self.good_rec = make_user('goodrec', 'recruiter')
        RecruiterProfile.objects.create(user=self.good_rec, company_name='Acme', verification_status='approved')
        self.bad_rec = make_user('badrec', 'recruiter')
        RecruiterProfile.objects.create(user=self.bad_rec, company_name='Shady', verification_status='pending')

    def get_as(self, user):
        self.client.force_login(user)
        return self.client.get(self.url)

    def test_owner_admin_and_verified_recruiter_are_redirected_to_file(self):
        for user in (self.owner, self.admin, self.good_rec):
            resp = self.get_as(user)
            self.assertEqual(resp.status_code, 302, user.username)
            self.assertEqual(resp['Location'], 'https://res.cloudinary.com/democloud/raw/upload/v1/resumes/abc123.pdf')
            self.assertIn('no-store', resp['Cache-Control'])

    def test_other_students_and_unverified_recruiters_are_forbidden(self):
        for user in (self.other, self.bad_rec):
            self.assertEqual(self.get_as(user).status_code, 403, user.username)

    def test_recruiter_without_profile_is_forbidden(self):
        self.assertEqual(self.get_as(make_user('noprof', 'recruiter')).status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_unknown_file_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('resume_download', kwargs={'name': 'resumes/nope.pdf'}))
        self.assertEqual(resp.status_code, 404)

    def test_profile_page_links_resume_through_the_gate(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, '/students/resume/resumes/abc123.pdf')
        self.assertNotContains(resp, 'res.cloudinary.com')


class LocalStorageFallbackTests(TestCase):
    """Without Cloudinary (local dev) the same view serves the local /media/ file."""

    def test_redirects_to_local_media_url(self):
        owner = make_user('owner', 'student')
        profile = StudentProfile.objects.create(user=owner, branch='CSE')
        StudentProfile.objects.filter(pk=profile.pk).update(resume='resumes/local.pdf')
        self.client.force_login(owner)
        resp = self.client.get(reverse('resume_download', kwargs={'name': 'resumes/local.pdf'}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/media/resumes/local.pdf')


class SearchStudentsAccessTests(TestCase):
    def test_unverified_recruiter_cannot_browse_students(self):
        rec = make_user('badrec', 'recruiter')
        RecruiterProfile.objects.create(user=rec, company_name='Shady', verification_status='pending')
        self.client.force_login(rec)
        resp = self.client.get(reverse('search_students'))
        self.assertRedirects(resp, reverse('verification_status'), fetch_redirect_response=False)

    def test_verified_recruiter_and_admin_can_browse(self):
        rec = make_user('goodrec', 'recruiter')
        RecruiterProfile.objects.create(user=rec, company_name='Acme', verification_status='approved')
        admin = make_user('boss', 'admin')
        for user in (rec, admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('search_students')).status_code, 200, user.username)

    def test_student_cannot_browse(self):
        self.client.force_login(make_user('stu', 'student'))
        resp = self.client.get(reverse('search_students'))
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)


@override_settings(STORAGES=CLOUD_STORAGES)
class ModelFieldUploadTests(TestCase):
    """The same path the profile form uses: assign a file to a model field and save."""

    def test_resume_and_picture_saved_via_model_fields(self):
        cloudinary.config(cloud_name='democloud', api_key='k', api_secret='s')
        calls = []

        def fake_request(method, url, fields=None, headers=None, **kw):
            f = dict((k, v) for k, v in fields if k != 'file')
            calls.append((url, f['public_id']))
            fmt = 'pdf' if '/raw/' in url else 'png'
            return FakeResponse({'public_id': f['public_id'], 'format': fmt, 'version': 1,
                                 'resource_type': 'raw' if '/raw/' in url else 'image',
                                 'type': 'upload', 'signature': 'x'})

        # 1x1 transparent PNG so ImageField validation passes
        png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4'
               b'\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82')
        user = make_user('stu', 'student')
        with mock.patch('cloudinary.uploader._http.request', fake_request):
            profile = StudentProfile(user=user, branch='CSE')
            profile.resume = SimpleUploadedFile('cv.pdf', b'%PDF-1.4 hello', content_type='application/pdf')
            profile.profile_pic = SimpleUploadedFile('me.png', png, content_type='image/png')
            profile.save()

        profile.refresh_from_db()
        self.assertRegex(profile.resume.name, r'^resumes/[0-9a-f]{32}\.pdf$')
        self.assertRegex(profile.profile_pic.name, r'^profile_pics/[0-9a-f]{32}\.png$')
        self.assertEqual(len(calls), 2)
        self.assertTrue(profile.resume.url.startswith('/students/resume/resumes/'))
        self.assertTrue(profile.profile_pic.url.startswith('https://res.cloudinary.com/democloud/image/upload/'))


class RejectedUploadTests(TestCase):
    """A rejected resume must not leave a bogus 'Current: View Resume' link behind."""

    def setUp(self):
        self.user = make_user('stu', 'student')
        self.profile = StudentProfile.objects.create(user=self.user, branch='CSE')
        self.client.force_login(self.user)

    def post_resume(self, upload):
        return self.client.post(reverse('edit_profile'), profile_data(resume=upload))

    def test_docx_is_rejected_with_message_and_no_phantom_link(self):
        docx = SimpleUploadedFile('My Resume.docx', b'PK\x03\x04 fake', content_type=
                                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp = self.post_resume(docx)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Resume must be a PDF file.')
        self.assertNotContains(resp, 'View Resume')
        self.assertNotContains(resp, 'My%20Resume.docx')
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.resume)

    def test_rejected_upload_keeps_the_previously_saved_resume(self):
        StudentProfile.objects.filter(pk=self.profile.pk).update(resume='resumes/old.pdf')
        resp = self.post_resume(SimpleUploadedFile('new.docx', b'PK fake'))
        self.assertContains(resp, 'Resume must be a PDF file.')
        self.assertContains(resp, 'resumes/old.pdf')
        self.assertNotContains(resp, 'new.docx')

    def test_oversized_pdf_is_rejected(self):
        big = SimpleUploadedFile('cv.pdf', b'%PDF-1.4' + b'0' * (2 * 1024 * 1024 + 1), content_type='application/pdf')
        self.assertContains(self.post_resume(big), 'smaller than 2 MB')

    def test_picker_only_offers_pdf(self):
        resp = self.client.get(reverse('edit_profile'))
        self.assertContains(resp, 'accept=".pdf,application/pdf"')
        self.assertNotContains(resp, '.docx"')


def png_bytes():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
    return buf.getvalue()


class ImageUploadValidationTests(TestCase):
    """Pictures must be real images: a Word file must never reach the storage service."""

    def setUp(self):
        self.user = make_user('stu', 'student')
        StudentProfile.objects.create(user=self.user, branch='CSE')
        self.client.force_login(self.user)

    def post_pic(self, upload):
        return self.client.post(reverse('edit_profile'), profile_data(profile_pic=upload))

    def test_docx_as_picture_is_rejected(self):
        resp = self.post_pic(SimpleUploadedFile('notes.docx', b'PK\x03\x04 fake', content_type='application/msword'))
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')

    def test_non_image_bytes_with_png_name_are_rejected(self):
        resp = self.post_pic(SimpleUploadedFile('sneaky.png', b'PK\x03\x04 this is a zip', content_type='image/png'))
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')

    def test_svg_is_rejected(self):
        resp = self.post_pic(SimpleUploadedFile('x.svg', b'<svg onload="alert(1)"/>', content_type='image/svg+xml'))
        self.assertContains(resp, 'JPG, PNG, GIF or WebP')

    def test_oversized_image_is_rejected(self):
        big = png_bytes() + b'0' * (2 * 1024 * 1024)
        self.assertContains(self.post_pic(SimpleUploadedFile('big.png', big, content_type='image/png')),
                            'smaller than 2 MB')

    def test_real_png_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            resp = self.post_pic(SimpleUploadedFile('me.png', png_bytes(), content_type='image/png'))
            self.assertEqual(resp.status_code, 302)
        self.assertTrue(StudentProfile.objects.get(user=self.user).profile_pic)


from django.test import TransactionTestCase


@override_settings(STORAGES=CLOUD_STORAGES)
class StorageFailureTests(TransactionTestCase):
    """A Cloudinary outage must give a friendly message, not a crashed page."""

    def setUp(self):
        cloudinary.config(cloud_name='democloud', api_key='k', api_secret='s')
        self.user = make_user('stu', 'student')
        StudentProfile.objects.create(user=self.user, branch='CSE')
        self.client.force_login(self.user)

    def test_upload_failure_redirects_back_with_message(self):
        import cloudinary.exceptions
        with mock.patch('cloudinary.uploader.upload', side_effect=cloudinary.exceptions.Error('boom')):
            resp = self.client.post(reverse('edit_profile'), profile_data(
                profile_pic=SimpleUploadedFile('me.png', png_bytes(), content_type='image/png')))
            self.assertRedirects(resp, reverse('edit_profile'), fetch_redirect_response=False)
            page = self.client.get(reverse('edit_profile'))
        self.assertContains(page, 'We could not save your file right now')
        self.assertFalse(StudentProfile.objects.get(user=self.user).profile_pic)

    def test_upload_uses_a_timeout(self):
        seen = {}

        def fake_request(method, url, fields=None, headers=None, **kw):
            seen.update(kw)
            f = dict((k, v) for k, v in fields if k != 'file')
            return FakeResponse({'public_id': f['public_id'], 'format': 'png', 'version': 1,
                                 'resource_type': 'image', 'type': 'upload', 'signature': 'x'})

        with mock.patch('cloudinary.uploader._http.request', fake_request):
            CloudinaryMediaStorage().save('profile_pics/a.png', SimpleUploadedFile('a.png', png_bytes()))
        self.assertEqual(seen.get('timeout'), 20)


class TestEnvironmentIsolationTests(SimpleTestCase):
    def test_tests_never_use_real_cloudinary_storage(self):
        """A developer's CLOUDINARY_URL must not leak into the test run (it would upload real files)."""
        from django.conf import settings
        self.assertNotIn('Cloudinary', settings.STORAGES['default']['BACKEND'])


# ───────────────────────── Orphaned-file cleanup ─────────────────────────
class FileCleanupTests(TestCase):
    """Replaced / deleted uploads must not pile up in storage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.user = make_user('stu', 'student')

    def path(self, name):
        return os.path.join(self._tmp.name, name)

    def make_profile(self):
        profile = StudentProfile(user=self.user, branch='CSE')
        profile.resume = SimpleUploadedFile('cv.pdf', b'%PDF-1.4 one', content_type='application/pdf')
        profile.save()
        return profile

    def test_replacing_a_resume_deletes_the_old_file(self):
        profile = self.make_profile()
        old = profile.resume.name
        self.assertTrue(os.path.exists(self.path(old)))
        profile.resume = SimpleUploadedFile('cv2.pdf', b'%PDF-1.4 two', content_type='application/pdf')
        with self.captureOnCommitCallbacks(execute=True):
            profile.save()
        self.assertNotEqual(profile.resume.name, old)
        self.assertFalse(os.path.exists(self.path(old)))
        self.assertTrue(os.path.exists(self.path(profile.resume.name)))

    def test_saving_without_changing_the_file_keeps_it(self):
        profile = self.make_profile()
        name = profile.resume.name
        profile.branch = 'ECE'
        profile.save()
        self.assertEqual(StudentProfile.objects.get(pk=profile.pk).resume.name, name)
        self.assertTrue(os.path.exists(self.path(name)))

    def test_clearing_a_file_deletes_it(self):
        profile = self.make_profile()
        name = profile.resume.name
        profile.resume = None
        with self.captureOnCommitCallbacks(execute=True):
            profile.save()
        self.assertFalse(os.path.exists(self.path(name)))

    def test_deleting_the_row_deletes_its_files(self):
        profile = self.make_profile()
        name = profile.resume.name
        with self.captureOnCommitCallbacks(execute=True):
            profile.delete()
        self.assertFalse(os.path.exists(self.path(name)))

    def test_rejected_upload_deletes_nothing(self):
        profile = self.make_profile()
        name = profile.resume.name
        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('edit_profile'), profile_data(
                resume=SimpleUploadedFile('bad.docx', b'PK fake')))
        self.assertTrue(os.path.exists(self.path(name)))
        self.assertEqual(StudentProfile.objects.get(pk=profile.pk).resume.name, name)

    def test_deleting_a_drive_removes_its_logo(self):
        from placements.models import PlacementDrive
        from django.utils import timezone
        rec = make_user('rec', 'recruiter')
        drive = PlacementDrive(posted_by=rec, company='A', role='R', description='d', location='L',
                               job_type='full_time', deadline=timezone.localdate())
        drive.company_logo = SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')
        drive.save()
        name = drive.company_logo.name
        self.assertTrue(os.path.exists(self.path(name)))
        with self.captureOnCommitCallbacks(execute=True):
            drive.delete()
        self.assertFalse(os.path.exists(self.path(name)))


@override_settings(STORAGES=CLOUD_STORAGES)
class CloudinaryCleanupTests(TestCase):
    def test_replacing_a_resume_destroys_the_old_cloudinary_file(self):
        cloudinary.config(cloud_name='democloud', api_key='k', api_secret='s')

        def fake_request(method, url, fields=None, headers=None, **kw):
            f = dict((k, v) for k, v in fields if k != 'file')
            return FakeResponse({'public_id': f['public_id'], 'format': 'pdf', 'version': 1,
                                 'resource_type': 'raw', 'type': 'upload', 'signature': 'x'})

        user = make_user('stu', 'student')
        with mock.patch('cloudinary.uploader._http.request', fake_request), \
                mock.patch('cloudinary.uploader.destroy') as destroy:
            profile = StudentProfile(user=user, branch='CSE')
            profile.resume = SimpleUploadedFile('a.pdf', b'%PDF-1.4 a', content_type='application/pdf')
            profile.save()
            old = profile.resume.name
            profile.resume = SimpleUploadedFile('b.pdf', b'%PDF-1.4 b', content_type='application/pdf')
            with self.captureOnCommitCallbacks(execute=True):
                profile.save()
        destroy.assert_called_once()
        self.assertEqual(destroy.call_args.args[0], old)
        self.assertEqual(destroy.call_args.kwargs['resource_type'], 'raw')
        self.assertNotEqual(profile.resume.name, old)


# ═════════════════════════ Phase D: profile completion + forms ═════════════════════════
class ProfileCompletenessTests(TestCase):
    def setUp(self):
        self.user = make_user('stu', 'student')

    def complete(self, **over):
        fields = dict(user=self.user, branch='CSE', cgpa=8.0, passing_year=2027, resume='resumes/x.pdf')
        fields.update(over)
        return StudentProfile.objects.create(**fields)

    def test_fresh_profile_is_missing_everything(self):
        profile = StudentProfile.objects.create(user=self.user)
        self.assertEqual(profile.missing_required_fields(), ['Branch', 'CGPA', 'Passing year', 'Resume (PDF)'])
        self.assertFalse(profile.is_complete)

    def test_new_profile_has_no_silent_defaults(self):
        self.client.force_login(self.user)
        self.client.get(reverse('profile'))
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(profile.branch, '')
        self.assertIsNone(profile.passing_year)
        self.assertEqual(profile.cgpa, 0.0)

    def test_complete_profile(self):
        profile = self.complete()
        self.assertTrue(profile.is_complete)
        self.assertEqual(profile.missing_required_fields(), [])

    def test_each_required_field_matters(self):
        cases = {'branch': ('', 'Branch'), 'cgpa': (0.0, 'CGPA'),
                 'passing_year': (None, 'Passing year'), 'resume': ('', 'Resume (PDF)')}
        for field, (empty, label) in cases.items():
            profile = self.complete(**{field: empty})
            self.assertEqual(profile.missing_required_fields(), [label], field)
            profile.delete()

    def test_phone_and_linkedin_are_not_required(self):
        profile = self.complete()
        self.assertEqual(profile.linkedin, '')
        self.assertEqual(self.user.phone, '')
        self.assertTrue(profile.is_complete)


class StudentProfileFormTests(TestCase):
    def setUp(self):
        self.user = make_user('stu', 'student')
        self.client.force_login(self.user)

    def post(self, **over):
        return self.client.post(reverse('edit_profile'), profile_data(**over))

    def profile(self):
        return StudentProfile.objects.get(user=self.user)

    def test_valid_save_updates_profile_name_and_phone(self):
        resp = self.post(first_name='Asha', last_name='Verma', phone='+91 98765 43210',
                         roll_number='21CSE001', skills='python', linkedin='https://linkedin.com/in/asha')
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name, self.user.phone), ('Asha', 'Verma', '+91 98765 43210'))
        profile = self.profile()
        self.assertEqual((profile.branch, profile.cgpa, profile.passing_year, profile.roll_number),
                         ('CSE', 8.0, 2027, '21CSE001'))

    def test_required_fields_cannot_be_blank(self):
        for field in ('branch', 'cgpa', 'passing_year', 'first_name'):
            resp = self.post(**{field: ''})
            self.assertEqual(resp.status_code, 200, field)
        self.assertFalse(StudentProfile.objects.filter(user=self.user, cgpa__gt=0).exists())

    def test_bad_cgpa_rejected(self):
        for bad in ('0', '-1', '10.5', '11', 'nan', 'inf', 'abc'):
            self.assertEqual(self.post(cgpa=bad).status_code, 200, bad)
        self.assertFalse(StudentProfile.objects.filter(user=self.user, cgpa__gt=0).exists())

    def test_cgpa_boundaries_accepted(self):
        for ok in ('0.01', '10', '7.55'):
            self.assertEqual(self.post(cgpa=ok).status_code, 302, ok)

    def test_bad_passing_year_rejected(self):
        for bad in ('1999', '2051', 'abc', '20.5'):
            self.assertEqual(self.post(passing_year=bad).status_code, 200, bad)

    def test_branch_must_be_a_real_student_branch(self):
        for bad in ('ALL', 'XYZ'):
            self.assertEqual(self.post(branch=bad).status_code, 200, bad)

    def test_bad_links_rejected(self):
        self.assertEqual(self.post(linkedin='not a url').status_code, 200)
        self.assertEqual(self.post(github='javascript:alert(1)').status_code, 200)

    def test_bad_phone_rejected_but_blank_is_fine(self):
        for bad in ('abc', '12', '1' * 20, '<script>'):
            self.assertEqual(self.post(phone=bad).status_code, 200, bad)
        self.assertEqual(self.post(phone='').status_code, 302)

    def test_blank_roll_number_is_stored_as_null_not_the_word_none(self):
        self.post(roll_number='')
        self.assertIsNone(self.profile().roll_number)
        # another student leaving it blank must not collide with the first
        other = make_user('stu2', 'student')
        self.client.force_login(other)
        self.assertEqual(self.post(roll_number='').status_code, 302)
        self.assertIsNone(StudentProfile.objects.get(user=other).roll_number)

    def test_duplicate_roll_number_rejected(self):
        self.post(roll_number='R1')
        other = make_user('stu2', 'student')
        self.client.force_login(other)
        resp = self.post(roll_number='R1')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_nothing_is_half_saved_when_profile_part_is_invalid(self):
        self.post(first_name='Changed', cgpa='99')
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.first_name, 'Changed')

    def test_edit_page_does_not_prefill_unset_values(self):
        resp = self.client.get(reverse('edit_profile'))
        html = resp.content.decode()
        self.assertNotIn('value="None"', html)
        self.assertNotIn('value="0.0"', html)
        self.assertIn('Select your branch', html)
        self.assertNotIn('All Branches', html)       # not a valid student branch
        self.assertContains(resp, 'Your profile is incomplete.')

    def test_edit_page_shows_saved_values(self):
        self.post(roll_number='21CSE009')
        html = self.client.get(reverse('edit_profile')).content.decode()
        self.assertIn('value="21CSE009"', html)
        self.assertIn('value="8.0"', html)
        self.assertIn('value="2027"', html)
        self.assertIn('<option value="CSE" selected>', html)


class ProfileBannerTests(TestCase):
    def setUp(self):
        from placements.models import PlacementDrive
        from datetime import timedelta
        from django.utils import timezone
        self.user = make_user('stu', 'student')
        self.client.force_login(self.user)
        rec = make_user('rec', 'recruiter')
        self.drive = PlacementDrive.objects.create(
            posted_by=rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.localdate() + timedelta(days=5))

    def make_complete(self):
        StudentProfile.objects.update_or_create(user=self.user, defaults=dict(
            branch='CSE', cgpa=8.0, passing_year=2027, resume='resumes/x.pdf'))

    def test_incomplete_student_sees_notice_everywhere_and_cannot_click_apply(self):
        for url in (reverse('profile'), reverse('dashboard')):
            resp = self.client.get(url)
            self.assertContains(resp, 'Your profile is incomplete.', msg_prefix=url)
            self.assertContains(resp, 'Branch, CGPA, Passing year, Resume (PDF)', msg_prefix=url)
        detail = self.client.get(reverse('drive_detail', args=[self.drive.pk]))
        self.assertContains(detail, 'Complete profile to apply')
        self.assertNotContains(detail, 'Apply Now')

    def test_complete_student_sees_no_notice_and_gets_apply_button(self):
        self.make_complete()
        for url in (reverse('profile'), reverse('dashboard')):
            self.assertNotContains(self.client.get(url), 'Your profile is incomplete.', msg_prefix=url)
        detail = self.client.get(reverse('drive_detail', args=[self.drive.pk]))
        self.assertContains(detail, 'Apply Now')
        self.assertNotContains(detail, 'Complete profile to apply')

    def test_partial_profile_lists_only_what_is_missing(self):
        StudentProfile.objects.create(user=self.user, branch='CSE', cgpa=8.0)
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'Passing year, Resume (PDF)')
        self.assertNotContains(resp, 'Branch, CGPA')


class RecruiterProfileFormTests(TestCase):
    def setUp(self):
        self.user = make_user('rec', 'recruiter')
        self.client.force_login(self.user)

    def post(self, **over):
        data = {'company_name': 'Acme', 'industry': 'Technology', 'designation': 'HR',
                'company_website': 'https://acme.example', 'company_address': 'Delhi',
                'about': 'We build', 'linkedin': 'https://linkedin.com/company/acme'}
        data.update(over)
        return self.client.post(reverse('edit_profile'), data)

    def test_valid_save(self):
        self.assertRedirects(self.post(), reverse('profile'), fetch_redirect_response=False)
        profile = RecruiterProfile.objects.get(user=self.user)
        self.assertEqual((profile.company_name, profile.industry), ('Acme', 'Technology'))

    def test_bad_values_rejected_and_nothing_saved(self):
        for over in ({'company_website': 'nope'}, {'linkedin': 'nope'}, {'industry': 'Piracy'},
                     {'company_name': 'x' * 101}):
            self.assertEqual(self.post(**over).status_code, 200, over)
        self.assertEqual(RecruiterProfile.objects.get(user=self.user).company_name, '')

    def test_everything_optional(self):
        self.assertEqual(self.post(company_name='', industry='', designation='', company_website='',
                                   company_address='', about='', linkedin='').status_code, 302)

    def test_non_image_picture_rejected(self):
        resp = self.post(profile_pic=SimpleUploadedFile('x.docx', b'PK fake'))
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')


class UntouchedProfileMigrationTests(TestCase):
    def test_only_untouched_profiles_are_blanked(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module('students.migrations.0012_clear_untouched_profile_defaults')
        def mk(name, **fields):
            return StudentProfile.objects.create(user=make_user(name, 'student'), **fields)
        untouched = mk('a', branch='CSE', passing_year=2026)
        has_cgpa = mk('b', branch='ECE', passing_year=2026, cgpa=7.5)
        has_skills = mk('c', branch='IT', passing_year=2026, skills='python')
        has_resume = mk('d', branch='ME', passing_year=2026, resume='resumes/x.pdf')
        has_roll = mk('e', branch='CE', passing_year=2026, roll_number='R9')
        migration.clear_untouched_defaults(apps, None)
        for p in (untouched, has_cgpa, has_skills, has_resume, has_roll):
            p.refresh_from_db()
        self.assertEqual((untouched.branch, untouched.passing_year), ('', None))
        self.assertEqual((has_cgpa.branch, has_cgpa.passing_year), ('ECE', 2026))
        self.assertEqual((has_skills.branch, has_skills.passing_year), ('IT', 2026))
        self.assertEqual((has_resume.branch, has_resume.passing_year), ('ME', 2026))
        self.assertEqual((has_roll.branch, has_roll.passing_year), ('CE', 2026))
