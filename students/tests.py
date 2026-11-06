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
        return self.client.post(reverse('edit_profile'), {'branch': 'CSE', 'resume': upload})

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
        return self.client.post(reverse('edit_profile'), {'branch': 'CSE', 'profile_pic': upload})

    def test_docx_as_picture_is_rejected(self):
        resp = self.post_pic(SimpleUploadedFile('notes.docx', b'PK\x03\x04 fake', content_type='application/msword'))
        self.assertContains(resp, 'Image must be a JPG, PNG, GIF or WebP file.')

    def test_non_image_bytes_with_png_name_are_rejected(self):
        resp = self.post_pic(SimpleUploadedFile('sneaky.png', b'PK\x03\x04 this is a zip', content_type='image/png'))
        self.assertContains(resp, 'This file is not a valid image.')

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
            resp = self.client.post(reverse('edit_profile'), {
                'branch': 'CSE',
                'profile_pic': SimpleUploadedFile('me.png', png_bytes(), content_type='image/png')})
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
            self.client.post(reverse('edit_profile'), {
                'branch': 'CSE', 'resume': SimpleUploadedFile('bad.docx', b'PK fake')})
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
