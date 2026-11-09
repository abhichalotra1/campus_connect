from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from notifications.models import Notification
from placements.models import Application, PlacementDrive
from students.models import StudentProfile

PW = 'Pass12345!x'


def _user(username, role='student', **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password=PW, role=role, **extra)


class Base(TestCase):
    def setUp(self):
        self.admin = _user('boss', 'admin')
        self.rec = _user('rec', 'recruiter')
        self.stu = _user('stu')
        StudentProfile.objects.create(user=self.stu, branch='CSE', cgpa=8.0)
        self.drive = PlacementDrive.objects.create(
            posted_by=self.rec, company='Acme', role='Dev', description='d', location='X',
            job_type='full_time', deadline=timezone.localdate() + timedelta(days=5))
        self.client.force_login(self.admin)


class PostDriveKeepsInputTests(Base):
    def test_error_keeps_what_was_typed(self):
        resp = self.client.post(reverse('post_drive'), {
            'company': 'KeepCo', 'role': 'Keeper', 'description': 'long text here',
            'location': 'Pune', 'job_type': 'internship', 'eligible_branch': 'ECE',
            'min_cgpa': '6.5', 'salary_type': 'stipend', 'salary_amount': '20',
            'deadline': '2099-01-01'})  # no logo -> invalid
        html = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        for text in ('KeepCo', 'Keeper', 'long text here', 'Pune', 'value="6.5"', '2099-01-01'):
            self.assertIn(text, html)
        self.assertRegex(html, r'<option value="internship"\s+selected')
        self.assertRegex(html, r'<option value="ECE"\s+selected')
        self.assertFalse(PlacementDrive.objects.filter(company='KeepCo').exists())

    def test_blank_form_still_renders(self):
        html = self.client.get(reverse('post_drive')).content.decode()
        self.assertIn('value="0.0"', html)
        self.assertNotIn('None', html.split('name="company"')[1][:80])

    def test_posting_is_audit_logged(self):
        from students.tests import png_bytes
        from django.core.files.uploadedfile import SimpleUploadedFile
        with self.settings(MEDIA_ROOT='/tmp/cc_media_test'):
            self.client.post(reverse('post_drive'), {
                'company': 'LogCo', 'role': 'R', 'description': 'd', 'location': 'L',
                'job_type': 'full_time', 'eligible_branch': 'ALL', 'min_cgpa': '0',
                'salary_type': 'not_disclosed', 'salary_amount': '',
                'deadline': (timezone.localdate() + timedelta(days=3)).isoformat(),
                'company_logo': SimpleUploadedFile('l.png', png_bytes(), content_type='image/png')})
        self.assertTrue(AuditLog.objects.filter(action='drive_posted', target__contains='LogCo').exists())


class DeleteDriveTests(Base):
    def test_drive_without_applications_can_be_deleted_and_is_logged(self):
        self.client.post(reverse('delete_drive', args=[self.drive.pk]))
        self.assertFalse(PlacementDrive.objects.filter(pk=self.drive.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='drive_deleted').exists())

    def test_drive_with_applications_cannot_be_deleted(self):
        Application.objects.create(student=self.stu, drive=self.drive)
        self.client.post(reverse('delete_drive', args=[self.drive.pk]))
        self.assertTrue(PlacementDrive.objects.filter(pk=self.drive.pk).exists())
        self.assertEqual(Application.objects.count(), 1)

    def test_confirm_page_warns_and_hides_button_when_applications_exist(self):
        Application.objects.create(student=self.stu, drive=self.drive)
        html = self.client.get(reverse('delete_drive', args=[self.drive.pk])).content.decode()
        self.assertIn('cannot be deleted', html)
        self.assertNotIn('Yes, Delete Drive', html)


class DriveToggleTests(Base):
    def test_close_and_reopen_are_logged(self):
        url = reverse('admin_toggle_drive', args=[self.drive.pk])
        self.client.post(url)
        self.client.post(url)
        actions = list(AuditLog.objects.values_list('action', flat=True))
        self.assertIn('drive_closed', actions)
        self.assertIn('drive_reopened', actions)

    def test_reopening_expired_drive_says_so(self):
        self.drive.status = 'closed'
        self.drive.deadline = timezone.localdate() - timedelta(days=2)
        self.drive.save()
        resp = self.client.post(reverse('admin_toggle_drive', args=[self.drive.pk]), follow=True)
        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertIn('deadline', text)
        self.assertIn('has passed', text)


class StatusChangeTests(Base):
    def setUp(self):
        super().setUp()
        self.app = Application.objects.create(student=self.stu, drive=self.drive)
        self.url = reverse('update_application', args=[self.app.pk])

    def test_change_notifies_once_and_is_logged(self):
        self.client.post(self.url, {'status': 'shortlisted'})
        self.assertEqual(Notification.objects.filter(user=self.stu).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='application_status_changed').count(), 1)

    def test_same_status_does_not_notify_or_email_again(self):
        self.client.post(self.url, {'status': 'shortlisted'})
        with mock.patch('accounts.views.send_status_update_email') as send:
            self.client.post(self.url, {'status': 'shortlisted'})
        send.assert_not_called()
        self.assertEqual(Notification.objects.filter(user=self.stu).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='application_status_changed').count(), 1)

    def test_revert_to_applied_wording(self):
        self.client.post(self.url, {'status': 'selected'})
        self.client.post(self.url, {'status': 'applied'})
        last = Notification.objects.filter(user=self.stu).order_by('-id').first()
        self.assertNotIn('has been applied', last.message)
        self.assertIn('under review', last.message)


class DeactivationRulesTests(Base):
    def test_cannot_deactivate_another_admin(self):
        other = _user('boss2', 'admin')
        self.client.post(reverse('admin_toggle_user', args=[other.pk]))
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_cannot_deactivate_self(self):
        self.client.post(reverse('admin_toggle_user', args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_deactivating_recruiter_closes_their_active_drives(self):
        closed_already = PlacementDrive.objects.create(
            posted_by=self.rec, company='B', role='R', description='d', location='X',
            job_type='full_time', status='closed',
            deadline=timezone.localdate() + timedelta(days=5))
        self.client.post(reverse('admin_toggle_user', args=[self.rec.pk]))
        self.rec.refresh_from_db()
        self.drive.refresh_from_db()
        self.assertFalse(self.rec.is_active)
        self.assertEqual(self.drive.status, 'closed')
        log = AuditLog.objects.get(action='user_deactivated')
        self.assertIn('1 active drive', log.details)

    def test_deactivating_student_leaves_drives_alone(self):
        self.client.post(reverse('admin_toggle_user', args=[self.stu.pk]))
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.status, 'active')

    def test_reactivating_recruiter_does_not_reopen_drives(self):
        self.client.post(reverse('admin_toggle_user', args=[self.rec.pk]))
        self.client.post(reverse('admin_toggle_user', args=[self.rec.pk]))
        self.rec.refresh_from_db()
        self.drive.refresh_from_db()
        self.assertTrue(self.rec.is_active)
        self.assertEqual(self.drive.status, 'closed')
