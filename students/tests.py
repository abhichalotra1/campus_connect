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
