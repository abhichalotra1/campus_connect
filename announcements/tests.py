from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from announcements.models import Announcement, AnnouncementReceipt
from announcements.services import audience_students, publish
from notifications.models import Notification
from placements.models import Application, PlacementDrive
from students.models import RecruiterProfile, StudentProfile

PW = 'Pass12345!x'


def make_user(username, role, **extra):
    return User.objects.create_user(username=username, email=f'{username}@example.com',
                                    password=PW, role=role, **extra)


def make_student(username, branch='CSE', cgpa=8.0):
    user = make_user(username, 'student')
    StudentProfile.objects.create(user=user, branch=branch, cgpa=cgpa)
    return user


def make_recruiter(username, approved=True):
    user = make_user(username, 'recruiter')
    RecruiterProfile.objects.create(
        user=user, company_name=f'{username} Corp',
        verification_status='approved' if approved else 'not_requested')
    return user


def make_drive(recruiter, **kw):
    defaults = dict(posted_by=recruiter, company='Acme', role='Dev', description='d', location='X',
                    job_type='full_time', deadline=timezone.localdate() + timedelta(days=5))
    defaults.update(kw)
    return PlacementDrive.objects.create(**defaults)


class AnnouncementBase(TestCase):
    def setUp(self):
        self.admin = make_user('boss', 'admin')
        self.rec = make_recruiter('rec')
        self.rec2 = make_recruiter('rec2')
        self.cse_hi = make_student('cse_hi', 'CSE', 9.0)
        self.cse_lo = make_student('cse_lo', 'CSE', 6.0)
        self.ece = make_student('ece', 'ECE', 8.5)
        self.drive = make_drive(self.rec, eligible_branch='CSE', min_cgpa=7.5)
        self.other_drive = make_drive(self.rec2, company='Other')

    def login(self, user):
        self.client.logout()
        self.client.force_login(user)

    def payload(self, **kw):
        data = {'title': 'Hello', 'message': 'Body text', 'audience': 'applicants',
                'drive': self.drive.pk, 'branch': ''}
        data.update(kw)
        return data


class AudienceTests(AnnouncementBase):
    def test_all_reaches_only_active_students(self):
        gone = make_student('gone')
        User.objects.filter(pk=gone.pk).update(is_active=False)
        names = set(audience_students('all').values_list('username', flat=True))
        self.assertEqual(names, {'cse_hi', 'cse_lo', 'ece'})  # no admin, no recruiters, no inactive

    def test_branch(self):
        names = set(audience_students('branch', branch='ECE').values_list('username', flat=True))
        self.assertEqual(names, {'ece'})

    def test_applicants_and_shortlisted(self):
        Application.objects.create(student=self.cse_hi, drive=self.drive, status='shortlisted')
        Application.objects.create(student=self.cse_lo, drive=self.drive, status='applied')
        Application.objects.create(student=self.ece, drive=self.other_drive, status='shortlisted')
        applicants = set(audience_students('applicants', drive=self.drive).values_list('username', flat=True))
        shortlisted = set(audience_students('shortlisted', drive=self.drive).values_list('username', flat=True))
        self.assertEqual(applicants, {'cse_hi', 'cse_lo'})
        self.assertEqual(shortlisted, {'cse_hi'})

    def test_eligible_respects_branch_and_cgpa(self):
        names = set(audience_students('eligible', drive=self.drive).values_list('username', flat=True))
        self.assertEqual(names, {'cse_hi'})  # cse_lo below CGPA, ece wrong branch

    def test_eligible_for_all_branches_drive(self):
        drive = make_drive(self.rec, eligible_branch='ALL', min_cgpa=8.0)
        names = set(audience_students('eligible', drive=drive).values_list('username', flat=True))
        self.assertEqual(names, {'cse_hi', 'ece'})

    def test_drive_audience_without_drive_reaches_nobody(self):
        self.assertEqual(audience_students('applicants').count(), 0)

    def test_student_applied_twice_is_not_duplicated(self):
        Application.objects.create(student=self.cse_hi, drive=self.drive)
        self.assertEqual(audience_students('applicants', drive=self.drive).count(), 1)


class PublishTests(AnnouncementBase):
    def test_publish_creates_receipts_and_notifications(self):
        ann = Announcement(author=self.admin, title='T', message='Line one', audience='all')
        publish(ann)
        ann.refresh_from_db()
        self.assertEqual(ann.recipients_count, 3)
        self.assertEqual(AnnouncementReceipt.objects.filter(announcement=ann).count(), 3)
        notes = Notification.objects.filter(notif_type='announcement')
        self.assertEqual(notes.count(), 3)
        self.assertTrue(notes.first().message.endswith('— Placement Cell'))
        self.assertFalse(Notification.objects.filter(user=self.rec).exists())

    def test_long_message_is_truncated_in_notification_only(self):
        ann = Announcement(author=self.admin, title='T', message='x' * 1000, audience='all')
        publish(ann)
        note = Notification.objects.filter(user=self.ece).get()
        self.assertLess(len(note.message), 320)
        self.assertEqual(len(Announcement.objects.get(pk=ann.pk).message), 1000)

    def test_recruiter_label_is_company_name(self):
        ann = Announcement(author=self.rec, title='T', message='m', audience='eligible', drive=self.drive)
        publish(ann)
        self.assertEqual(ann.author_label, 'rec Corp')

    def test_email_sent_in_bcc(self):
        ann = Announcement(author=self.admin, title='Big news', message='m', audience='all', send_email=True)
        with self.captureOnCommitCallbacks(execute=True):
            _, emailed = publish(ann)
        self.assertTrue(emailed)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].bcc),
                         {'cse_hi@example.com', 'cse_lo@example.com', 'ece@example.com'})
        self.assertIn('Big news', mail.outbox[0].subject)

    @override_settings(ANNOUNCEMENT_EMAIL_LIMIT=2)
    def test_email_skipped_for_large_audience(self):
        ann = Announcement(author=self.admin, title='T', message='m', audience='all', send_email=True)
        with self.captureOnCommitCallbacks(execute=True):
            _, emailed = publish(ann)
        self.assertFalse(emailed)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.filter(notif_type='announcement').count(), 3)  # still notified


class CreatePermissionTests(AnnouncementBase):
    url = property(lambda self: reverse('announcement_create'))

    def test_login_required(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_student_cannot_open_or_post(self):
        self.login(self.cse_hi)
        self.assertRedirects(self.client.get(self.url), reverse('announcements'), fetch_redirect_response=False)
        self.client.post(self.url, self.payload(audience='eligible'))
        self.assertFalse(Announcement.objects.exists())

    def test_unverified_recruiter_is_sent_to_verification(self):
        pending = make_recruiter('pending', approved=False)
        self.login(pending)
        self.assertRedirects(self.client.get(self.url), reverse('verification_status'), fetch_redirect_response=False)
        self.client.post(self.url, self.payload())
        self.assertFalse(Announcement.objects.exists())

    def test_verified_recruiter_can_send_to_own_drive_applicants(self):
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        self.login(self.rec)
        resp = self.client.post(self.url, self.payload())
        self.assertRedirects(resp, reverse('announcements'), fetch_redirect_response=False)
        ann = Announcement.objects.get()
        self.assertEqual((ann.author, ann.recipients_count), (self.rec, 1))
        self.assertTrue(AuditLog.objects.filter(action='announcement_sent').exists())
        self.assertTrue(Notification.objects.filter(user=self.admin, title='Announcement sent').exists())

    def test_recruiter_cannot_broadcast_to_all_or_branch(self):
        self.login(self.rec)
        self.client.post(self.url, self.payload(audience='all'))
        self.client.post(self.url, self.payload(audience='branch', branch='CSE'))
        self.assertFalse(Announcement.objects.exists())

    def test_recruiter_cannot_use_another_recruiters_drive(self):
        Application.objects.create(student=self.ece, drive=self.other_drive)
        self.login(self.rec)
        self.client.post(self.url, self.payload(drive=self.other_drive.pk))
        self.assertFalse(Announcement.objects.exists())

    def test_admin_can_broadcast_to_everyone(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='all', drive=''))
        self.assertEqual(Announcement.objects.get().recipients_count, 3)

    def test_admin_branch_audience_needs_branch(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='branch', drive='', branch=''))
        self.assertFalse(Announcement.objects.exists())
        self.client.post(self.url, self.payload(audience='branch', drive='', branch='ECE'))
        self.assertEqual(Announcement.objects.get().recipients_count, 1)

    def test_drive_audience_needs_drive(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='applicants', drive=''))
        self.assertFalse(Announcement.objects.exists())

    def test_nothing_is_sent_when_no_students_match(self):
        self.login(self.rec)
        self.client.post(self.url, self.payload())  # nobody applied yet
        self.assertFalse(Announcement.objects.exists())
        self.assertFalse(Notification.objects.filter(notif_type='announcement').exists())

    def test_recruiter_cannot_pin(self):
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        self.login(self.rec)
        self.client.post(self.url, self.payload(is_pinned='on'))
        self.assertFalse(Announcement.objects.get().is_pinned)

    def test_recruiter_daily_limit(self):
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        self.login(self.rec)
        with override_settings(ANNOUNCEMENT_RECRUITER_DAILY_LIMIT=2):
            for i in range(3):
                self.client.post(self.url, self.payload(title=f'T{i}'))
        self.assertEqual(Announcement.objects.count(), 2)

    def test_admin_has_no_daily_limit(self):
        self.login(self.admin)
        with override_settings(ANNOUNCEMENT_RECRUITER_DAILY_LIMIT=1):
            for i in range(3):
                self.client.post(self.url, self.payload(audience='all', drive='', title=f'T{i}'))
        self.assertEqual(Announcement.objects.count(), 3)

    def test_title_and_message_are_trimmed_and_required(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='all', drive='', title='   ', message='x'))
        self.assertFalse(Announcement.objects.exists())
        self.client.post(self.url, self.payload(audience='all', drive='', title='  Hi  ', message='  yo  '))
        ann = Announcement.objects.get()
        self.assertEqual((ann.title, ann.message), ('Hi', 'yo'))


class FeedTests(AnnouncementBase):
    def test_student_sees_only_announcements_sent_to_them(self):
        Application.objects.create(student=self.cse_hi, drive=self.drive)
        publish(Announcement(author=self.rec, title='For applicants', message='m',
                             audience='applicants', drive=self.drive))
        self.login(self.cse_hi)
        self.assertContains(self.client.get(reverse('announcements')), 'For applicants')
        self.login(self.ece)
        self.assertNotContains(self.client.get(reverse('announcements')), 'For applicants')

    def test_expired_announcement_hidden_from_students(self):
        publish(Announcement(author=self.admin, title='Old news', message='m', audience='all',
                             expires_at=timezone.localdate() - timedelta(days=1)))
        publish(Announcement(author=self.admin, title='Fresh news', message='m', audience='all',
                             expires_at=timezone.localdate()))
        self.login(self.ece)
        resp = self.client.get(reverse('announcements'))
        self.assertNotContains(resp, 'Old news')
        self.assertContains(resp, 'Fresh news')

    def test_message_is_escaped(self):
        publish(Announcement(author=self.admin, title='<b>x</b>', message='<script>alert(1)</script>',
                             audience='all'))
        self.login(self.ece)
        resp = self.client.get(reverse('announcements'))
        self.assertNotContains(resp, '<script>alert(1)</script>')
        self.assertContains(resp, '&lt;script&gt;')

    def test_dashboard_card_for_students(self):
        publish(Announcement(author=self.admin, title='Dash banner', message='m', audience='all',
                             is_pinned=True))
        self.login(self.ece)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="dash-announcements"')
        self.assertContains(resp, 'Dash banner')

    def test_dashboard_has_no_card_when_nothing_sent(self):
        self.login(self.ece)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'id="dash-announcements"')

    def test_notifications_page_renders_announcement_type(self):
        publish(Announcement(author=self.admin, title='Notice me', message='m', audience='all'))
        self.login(self.ece)
        resp = self.client.get(reverse('notifications'))
        self.assertContains(resp, 'Notice me')
        self.assertContains(resp, 'Announcement')

    def test_staff_manage_pages_render(self):
        publish(Announcement(author=self.rec, title='Mine', message='m', audience='eligible', drive=self.drive))
        publish(Announcement(author=self.rec2, title='Theirs', message='m', audience='eligible',
                             drive=self.other_drive))
        self.login(self.rec)
        resp = self.client.get(reverse('announcements'))
        self.assertContains(resp, 'Mine')
        self.assertNotContains(resp, 'Theirs')  # recruiters only manage their own
        self.login(self.admin)
        resp = self.client.get(reverse('announcements'))
        self.assertContains(resp, 'Mine')
        self.assertContains(resp, 'Theirs')

    def test_create_page_renders_for_admin_and_recruiter(self):
        for user in (self.admin, self.rec):
            self.login(user)
            self.assertEqual(self.client.get(reverse('announcement_create')).status_code, 200)

    def test_recruiter_form_hides_admin_only_choices(self):
        self.login(self.rec)
        html = self.client.get(reverse('announcement_create')).content.decode()
        self.assertNotIn('value="all"', html)
        self.assertNotIn('is_pinned', html)
        self.assertIn('Acme — Dev', html)               # their own drive is offered
        self.assertNotIn('Other — Dev', html)           # another recruiter's drive is not
        self.login(self.admin)
        html = self.client.get(reverse('announcement_create')).content.decode()
        self.assertIn('value="all"', html)
        self.assertIn('Other — Dev', html)              # admins see every drive


class DeleteAndPinTests(AnnouncementBase):
    def setUp(self):
        super().setUp()
        self.ann = Announcement(author=self.rec, title='T', message='m', audience='eligible', drive=self.drive)
        publish(self.ann)

    def test_get_is_not_allowed(self):
        self.login(self.rec)
        self.assertEqual(self.client.get(reverse('announcement_delete', args=[self.ann.pk])).status_code, 405)

    def test_author_can_delete_and_students_lose_it(self):
        self.login(self.rec)
        self.client.post(reverse('announcement_delete', args=[self.ann.pk]))
        self.assertFalse(Announcement.objects.exists())
        self.assertFalse(AnnouncementReceipt.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action='announcement_deleted').exists())

    def test_other_recruiter_cannot_delete(self):
        self.login(self.rec2)
        self.client.post(reverse('announcement_delete', args=[self.ann.pk]))
        self.assertTrue(Announcement.objects.exists())

    def test_student_cannot_delete(self):
        self.login(self.cse_hi)
        self.client.post(reverse('announcement_delete', args=[self.ann.pk]))
        self.assertTrue(Announcement.objects.exists())

    def test_admin_can_delete_anything(self):
        self.login(self.admin)
        self.client.post(reverse('announcement_delete', args=[self.ann.pk]))
        self.assertFalse(Announcement.objects.exists())

    def test_only_admin_can_pin(self):
        url = reverse('announcement_toggle_pin', args=[self.ann.pk])
        self.login(self.rec)
        self.client.post(url)
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_pinned)
        self.login(self.admin)
        self.client.post(url)
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_pinned)
        self.client.post(url)
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_pinned)

    def test_deleting_a_drive_keeps_the_announcement(self):
        self.drive.delete()
        self.ann.refresh_from_db()
        self.assertIsNone(self.ann.drive)


class ReviewFixTests(AnnouncementBase):
    """Regressions for problems found while reviewing the feature."""
    url = property(lambda self: reverse('announcement_create'))

    def test_multiline_message_counts_a_line_break_as_one_character(self):
        self.login(self.admin)
        typed = '\r\n'.join(['a' * 18] * 105)       # 1994 characters in the browser, 2098 with CRLF on the wire
        self.client.post(self.url, self.payload(audience='all', drive='', message=typed))
        ann = Announcement.objects.get()
        self.assertNotIn('\r', ann.message)
        self.assertEqual(len(ann.message), 1994)

    def test_message_over_the_limit_is_still_rejected(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='all', drive='', message='a' * 2001))
        self.assertFalse(Announcement.objects.exists())

    def test_title_is_collapsed_to_a_single_line(self):
        self.login(self.admin)
        self.client.post(self.url, self.payload(audience='all', drive='', title='Hello\r\n  there\tworld'))
        self.assertEqual(Announcement.objects.get().title, 'Hello there world')

    def test_past_expiry_date_is_rejected(self):
        self.login(self.admin)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.client.post(self.url, self.payload(audience='all', drive='', expires_at=yesterday))
        self.assertFalse(Announcement.objects.exists())
        today = timezone.localdate().isoformat()
        self.client.post(self.url, self.payload(audience='all', drive='', expires_at=today))
        self.assertEqual(Announcement.objects.count(), 1)

    def test_each_form_error_is_shown_once(self):
        self.login(self.admin)
        resp = self.client.post(self.url, self.payload(audience='branch', drive='', branch=''))
        self.assertContains(resp, 'Choose which branch to send to.', count=1)

    def test_errors_keep_what_was_typed(self):
        self.login(self.admin)
        resp = self.client.post(self.url, self.payload(audience='branch', drive='', branch='', title='Keep me'))
        self.assertContains(resp, 'Keep me')
        self.assertContains(resp, 'name="audience" value="branch" data-label="Students of one branch" checked')

    def _feed_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse('announcements')).status_code, 200)
        return len(ctx)

    def test_feed_query_count_does_not_grow_with_the_number_of_announcements(self):
        def send(i):
            recruiter = make_recruiter(f'bulk{i}')
            drive = make_drive(recruiter, company=f'Co{i}')
            Application.objects.create(student=self.ece, drive=drive)
            publish(Announcement(author=recruiter, title=f'A{i}', message='m', audience='applicants', drive=drive))
        send(0)
        self.login(self.ece)
        one = self._feed_queries()
        for i in range(1, 6):
            send(i)
        self.assertEqual(self._feed_queries(), one)

    def test_links_in_messages_are_clickable_and_still_escaped(self):
        publish(Announcement(author=self.admin, title='Link', audience='all',
                             message='Join https://meet.example.com/abc <b>now</b>'))
        self.login(self.ece)
        resp = self.client.get(reverse('announcements'))
        self.assertContains(resp, 'href="https://meet.example.com/abc"')
        self.assertContains(resp, '&lt;b&gt;now&lt;/b&gt;')


class ComposePageTests(AnnouncementBase):
    def test_page_shows_sender_and_only_allowed_audience_cards(self):
        self.login(self.rec)
        html = self.client.get(reverse('announcement_create')).content.decode()
        self.assertIn('rec Corp', html)                        # preview shows the recruiter's company as sender
        for value in ('eligible', 'applicants', 'shortlisted'):
            self.assertIn(f'name="audience" value="{value}"', html)
        for value in ('all', 'branch'):
            self.assertNotIn(f'name="audience" value="{value}"', html)
        self.assertIn('more announcement', html)               # daily-limit hint for recruiters

    def test_admin_sees_every_audience_card_and_placement_cell_sender(self):
        self.login(self.admin)
        html = self.client.get(reverse('announcement_create')).content.decode()
        for value in ('all', 'branch', 'eligible', 'applicants', 'shortlisted'):
            self.assertIn(f'name="audience" value="{value}"', html)
        self.assertIn('Placement Cell', html)
        self.assertNotIn('more announcement', html)            # admins have no daily limit

    def test_recruiter_daily_limit_hint_counts_down(self):
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        self.login(self.rec)
        with override_settings(ANNOUNCEMENT_RECRUITER_DAILY_LIMIT=3):
            self.client.post(reverse('announcement_create'), self.payload())
            html = self.client.get(reverse('announcement_create')).content.decode()
        self.assertIn('You can send 2 more announcements', html)


class AudienceCountTests(AnnouncementBase):
    url = property(lambda self: reverse('announcement_audience_count'))

    def count(self, **params):
        resp = self.client.get(self.url, params)
        self.assertEqual(resp.status_code, 200)
        return resp.json()['count']

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self.url, {'audience': 'all'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_students_and_unverified_recruiters_are_refused(self):
        self.login(self.cse_hi)
        self.assertEqual(self.client.get(self.url, {'audience': 'all'}).status_code, 403)
        self.login(make_recruiter('pending', approved=False))
        self.assertEqual(self.client.get(self.url, {'audience': 'all'}).status_code, 403)

    def test_admin_counts(self):
        self.login(self.admin)
        self.assertEqual(self.count(audience='all'), 3)
        self.assertEqual(self.count(audience='branch', branch='ECE'), 1)
        self.assertEqual(self.count(audience='eligible', drive=self.drive.pk), 1)   # only cse_hi qualifies
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        self.assertEqual(self.count(audience='applicants', drive=self.drive.pk), 1)
        self.assertEqual(self.count(audience='shortlisted', drive=self.drive.pk), 0)

    def test_incomplete_choices_have_no_count(self):
        self.login(self.admin)
        self.assertIsNone(self.count(audience='branch'))
        self.assertIsNone(self.count(audience='branch', branch='XYZ'))
        self.assertIsNone(self.count(audience='applicants'))
        self.assertIsNone(self.count(audience='nonsense'))
        self.assertIsNone(self.count())

    def test_recruiter_only_counts_for_their_own_drives_and_allowed_audiences(self):
        Application.objects.create(student=self.cse_lo, drive=self.drive)
        Application.objects.create(student=self.ece, drive=self.other_drive)
        self.login(self.rec)
        self.assertEqual(self.count(audience='applicants', drive=self.drive.pk), 1)
        self.assertIsNone(self.count(audience='applicants', drive=self.other_drive.pk))   # not their drive
        self.assertIsNone(self.count(audience='all'))                                      # admin-only audience
        self.assertIsNone(self.count(audience='branch', branch='CSE'))

    def test_garbage_drive_ids_do_not_crash(self):
        self.login(self.admin)
        for bad in ('abc', '', '-1', '1e3', '²', '9' * 40):
            self.assertIsNone(self.count(audience='applicants', drive=bad))

    def test_response_is_not_cached(self):
        self.login(self.admin)
        self.assertIn('no-store', self.client.get(self.url, {'audience': 'all'})['Cache-Control'])
