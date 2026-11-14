import io
import os
import tempfile
from datetime import date
from unittest import mock

import pypdf
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from campus_connect.storage import StorageUnavailable
from students.models import Achievement, Education, Experience, Project, StudentProfile
from students.resume import SECTION_LIMITS, bullets, build_resume
from students.resume_pdf import generate_resume_pdf
from students.validators import validate_resume

PW = 'Pass12345!x'


def make_user(username, role='student', **extra):
    return User.objects.create_user(username=username, email=f'{username}@example.com',
                                    password=PW, role=role, **extra)


def make_student(username, **extra):
    user = make_user(username, first_name='Asha', last_name='Verma', phone='+91 98765 43210')
    profile = StudentProfile.objects.create(user=user, branch='CSE', cgpa=8.4, passing_year=2027, **extra)
    return user, profile


def pdf_text(data):
    reader = pypdf.PdfReader(io.BytesIO(data))
    return '\n'.join(page.extract_text() for page in reader.pages), len(reader.pages)


EDUCATION = {'institution': 'Punjab Engineering College', 'degree': 'B.Tech',
             'field_of_study': 'Computer Science', 'start_year': '2023', 'end_year': '2027', 'grade': '8.4 CGPA'}


class AccessTests(TestCase):
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse('resume_builder'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_student_sees_builder_with_sidebar_link(self):
        user, _ = make_student('stu_a')
        self.client.force_login(user)
        response = self.client.get(reverse('resume_builder'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Resume Builder')
        self.assertContains(response, reverse('resume_builder'))
        self.assertContains(response, 'Asha Verma')            # pre-filled from the profile

    def test_recruiter_and_admin_are_refused(self):
        for role in ('recruiter', 'admin'):
            user = make_user(f'user_{role}', role)
            self.client.force_login(user)
            for url in (reverse('resume_builder'), reverse('resume_preview_pdf')):
                response = self.client.get(url)
                self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
            for url in (reverse('resume_entry_add', args=['education']), reverse('resume_generate')):
                response = self.client.post(url, EDUCATION)
                self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
            self.assertEqual(Education.objects.count(), 0)
            self.assertFalse(StudentProfile.objects.filter(user=user).exists())

    def test_sidebar_link_hidden_from_recruiters(self):
        self.client.force_login(make_user('rec_side', 'recruiter'))
        self.assertNotContains(self.client.get(reverse('dashboard')), reverse('resume_builder'))


class EntryTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_student('stu_a')
        self.client.force_login(self.user)

    def add_education(self, **extra):
        return self.client.post(reverse('resume_entry_add', args=['education']), {**EDUCATION, **extra})

    def test_add_edit_delete_education(self):
        self.assertRedirects(self.add_education(), reverse('resume_builder') + '#education',
                             fetch_redirect_response=False)
        entry = Education.objects.get()
        self.assertEqual(entry.profile, self.profile)

        self.client.post(reverse('resume_entry_edit', args=['education', entry.pk]),
                         {**EDUCATION, 'grade': '9.0 CGPA'})
        entry.refresh_from_db()
        self.assertEqual(entry.grade, '9.0 CGPA')
        self.assertEqual(Education.objects.count(), 1)

        self.client.post(reverse('resume_entry_delete', args=['education', entry.pk]))
        self.assertEqual(Education.objects.count(), 0)

    def test_add_every_kind(self):
        post = lambda kind, data: self.client.post(reverse('resume_entry_add', args=[kind]), data)
        post('experience', {'role': 'Intern', 'company': 'Infosys', 'start_date': '2025-06',
                            'end_date': '2025-08', 'description': '- Built an API\n* Fixed 12 bugs'})
        post('projects', {'title': 'Campus Connect', 'tech': 'Django', 'link': 'https://github.com/a/b',
                          'description': 'Placement portal'})
        post('achievements', {'text': 'Hackathon winner'})
        self.assertEqual(Experience.objects.get().start_date, date(2025, 6, 1))
        self.assertEqual(Project.objects.get().link, 'https://github.com/a/b')
        self.assertEqual(Achievement.objects.get().text, 'Hackathon winner')

    def test_new_entries_go_to_the_end_and_can_be_reordered(self):
        for name in ('A', 'B', 'C'):
            self.add_education(institution=name)
        a, b, c = Education.objects.order_by('position', 'id')
        self.assertLess(a.position, b.position)
        self.assertLess(b.position, c.position)

        self.client.post(reverse('resume_entry_move', args=['education', c.pk, 'up']))
        self.assertEqual([e.institution for e in Education.objects.all()], ['A', 'C', 'B'])
        self.client.post(reverse('resume_entry_move', args=['education', a.pk, 'down']))
        self.assertEqual([e.institution for e in Education.objects.all()], ['C', 'A', 'B'])
        # moving past either end changes nothing
        self.client.post(reverse('resume_entry_move', args=['education', c.pk, 'up']))
        self.assertEqual([e.institution for e in Education.objects.all()], ['C', 'A', 'B'])

    def test_moves_work_even_when_positions_tie(self):
        Education.objects.create(profile=self.profile, institution='A', degree='x', position=0)
        Education.objects.create(profile=self.profile, institution='B', degree='x', position=0)
        second = Education.objects.order_by('position', 'id')[1]
        self.client.post(reverse('resume_entry_move', args=['education', second.pk, 'up']))
        self.assertEqual([e.institution for e in Education.objects.all()], ['B', 'A'])

    def test_unknown_section_and_direction_are_404(self):
        self.assertEqual(self.client.post(reverse('resume_entry_add', args=['hobbies']), {}).status_code, 404)
        self.add_education()
        pk = Education.objects.get().pk
        self.assertEqual(self.client.post(reverse('resume_entry_move', args=['education', pk, 'left'])).status_code, 404)

    def test_get_is_not_allowed_on_changing_urls(self):
        self.add_education()
        pk = Education.objects.get().pk
        for name, args in (('resume_entry_delete', ['education', pk]), ('resume_entry_move', ['education', pk, 'up']),
                           ('resume_entry_add', ['education']), ('resume_generate', [])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 405)
        self.assertEqual(Education.objects.count(), 1)

    def test_limit_is_enforced(self):
        for i in range(SECTION_LIMITS['achievements']):
            self.client.post(reverse('resume_entry_add', args=['achievements']), {'text': f'Win {i}'})
        response = self.client.post(reverse('resume_entry_add', args=['achievements']), {'text': 'One too many'}, follow=True)
        self.assertEqual(Achievement.objects.count(), SECTION_LIMITS['achievements'])
        self.assertContains(response, 'You can add up to')

    def test_invalid_input_shows_errors_and_saves_nothing(self):
        bad_years = self.add_education(start_year='2027', end_year='2023')
        self.assertEqual(bad_years.status_code, 200)
        self.assertContains(bad_years, 'End year cannot be before the start year.')

        emoji = self.add_education(institution='College 🎓')
        self.assertContains(emoji, 'Emoji and non-Latin scripts')

        no_end = self.client.post(reverse('resume_entry_add', args=['experience']),
                                  {'role': 'Intern', 'company': 'X', 'start_date': '2025-06'})
        self.assertContains(no_end, 'Add an end month')
        self.assertEqual(Education.objects.count() + Experience.objects.count(), 0)

    def test_current_job_needs_no_end_month(self):
        self.client.post(reverse('resume_entry_add', args=['experience']),
                         {'role': 'Intern', 'company': 'X', 'start_date': '2025-06',
                          'end_date': '2025-09', 'is_current': 'on'})
        job = Experience.objects.get()
        self.assertTrue(job.is_current)
        self.assertIsNone(job.end_date)
        self.assertIn('Present', build_resume(self.profile)['experience'][0]['dates'])

    def test_text_fields_are_stored_literally_and_escaped_on_the_page(self):
        self.client.post(reverse('resume_entry_add', args=['achievements']), {'text': '<script>alert(1)</script>'})
        self.assertNotContains(self.client.get(reverse('resume_builder')), '<script>alert(1)</script>')


class OwnershipTests(TestCase):
    def setUp(self):
        self.owner, owner_profile = make_student('owner')
        self.other, _ = make_student('other')
        self.entry = Education.objects.create(profile=owner_profile, institution='Secret College', degree='B.Tech')

    def test_other_student_cannot_edit_delete_or_move(self):
        self.client.force_login(self.other)
        edit = self.client.post(reverse('resume_entry_edit', args=['education', self.entry.pk]),
                                {**EDUCATION, 'institution': 'Hacked'})
        delete = self.client.post(reverse('resume_entry_delete', args=['education', self.entry.pk]))
        move = self.client.post(reverse('resume_entry_move', args=['education', self.entry.pk, 'down']))
        self.assertEqual((edit.status_code, delete.status_code, move.status_code), (404, 404, 404))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.institution, 'Secret College')

    def test_other_student_does_not_see_the_entry_anywhere(self):
        self.client.force_login(self.other)
        page = self.client.get(reverse('resume_builder'))
        self.assertNotContains(page, 'Secret College')
        self.assertNotContains(self.client.get(reverse('resume_builder'), {'edit': f'education-{self.entry.pk}'}),
                               'Secret College')
        self.assertEqual(self.client.get(reverse('resume_preview_pdf')).status_code, 302)   # nothing to build

    def test_malformed_edit_parameter_is_ignored(self):
        self.client.force_login(self.owner)
        for value in ('', 'education', 'education-x', 'nope-1', '-', 'education-99999'):
            self.assertEqual(self.client.get(reverse('resume_builder'), {'edit': value}).status_code, 200)

    def test_edit_link_opens_the_form_for_the_owner(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse('resume_builder'), {'edit': f'education-{self.entry.pk}'})
        self.assertContains(page, 'Save changes')
        self.assertContains(page, 'value="Secret College"')


class ResumeDataTests(TestCase):
    def test_profile_details_are_prefilled(self):
        _, profile = make_student('prefill', skills='Python, Django, python', certifications='AWS CCP\nGCP ACE',
                                  about='Final-year student.', linkedin='https://www.linkedin.com/in/asha',
                                  github='https://github.com/asha')
        data = build_resume(profile)
        self.assertEqual(data['name'], 'Asha Verma')
        self.assertEqual(data['skills'], ['Python', 'Django'])            # de-duplicated
        self.assertEqual(data['certifications'], ['AWS CCP', 'GCP ACE'])
        self.assertEqual([c['text'] for c in data['contact']],
                         ['prefill@example.com', '+91 98765 43210', 'linkedin.com/in/asha', 'github.com/asha'])
        self.assertFalse(data['has_content'])                              # nothing to print yet

    def test_first_education_form_starts_from_the_profile(self):
        user, _ = make_student('init')
        self.client.force_login(user)
        page = self.client.get(reverse('resume_builder'))
        self.assertContains(page, 'value="Computer Science"')
        self.assertContains(page, 'value="8.4 CGPA"')
        self.assertContains(page, 'value="2027"')

    def test_bullets_clean_up_prefixes_and_cap_length(self):
        text = '- one\n* two\n\u2022 three\n\n   \nfour\n' + 'five\n' * 10
        self.assertEqual(bullets(text)[:4], ['one', 'two', 'three', 'four'])
        self.assertEqual(len(bullets(text)), 6)
        self.assertLessEqual(len(bullets('x' * 1000)[0]), 220)


class GenerateTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_student('gen', skills='Python, Django', about='Builder of things.')
        self.client.force_login(self.user)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        Education.objects.create(profile=self.profile, institution='PEC', degree='B.Tech', start_year=2023, end_year=2027)

    def generate(self, **data):
        return self.client.post(reverse('resume_generate'), data, follow=True)

    def test_needs_some_content(self):
        Education.objects.all().delete()
        response = self.generate(confirm='1')
        self.assertContains(response, 'Add an education, experience or project entry')
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.resume)

    def test_generates_a_valid_pdf_into_the_resume_field(self):
        self.assertIn('Resume (PDF)', self.profile.missing_required_fields())
        response = self.generate(confirm='1')
        self.assertContains(response, 'Resume generated and saved')
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.resume)
        self.assertNotIn('Resume (PDF)', self.profile.missing_required_fields())   # checklist updates
        self.assertTrue(self.profile.is_complete)

        with open(self.profile.resume.path, 'rb') as handle:
            data = handle.read()
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertLess(len(data), 2 * 1024 * 1024)
        validate_resume(ContentFile(data, name='resume.pdf'))                       # the upload rules accept it
        text, pages = pdf_text(data)
        self.assertEqual(pages, 1)
        for expected in ('Asha Verma', 'EDUCATION', 'PEC', 'Python, Django', 'Builder of things.'):
            self.assertIn(expected, text)

    def test_generated_resume_is_offered_and_keeps_the_existing_download_rules(self):
        self.generate(confirm='1')
        self.profile.refresh_from_db()
        self.assertContains(self.client.get(reverse('resume_builder')), 'View current resume')
        url = reverse('resume_download', kwargs={'name': self.profile.resume.name})
        self.assertEqual(self.client.get(url).status_code, 302)          # the student may download it
        self.client.force_login(make_student('nosy')[0])
        self.assertEqual(self.client.get(url).status_code, 403)          # another student may not

    def test_replacing_needs_confirmation_and_cleans_up_the_old_file(self):
        self.profile.resume.save('mine.pdf', ContentFile(b'%PDF-1.4 uploaded by the student'), save=True)
        old_path = self.profile.resume.path
        self.assertTrue(os.path.exists(old_path))

        refused = self.generate()                                                    # no confirm field
        self.assertContains(refused, 'Confirm that you want to replace it')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume.path, old_path)

        with self.captureOnCommitCallbacks(execute=True):
            self.generate(confirm='1')
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.resume.path, old_path)
        self.assertFalse(os.path.exists(old_path))                                   # old upload deleted
        self.assertTrue(os.path.exists(self.profile.resume.path))

    def test_storage_failure_gives_a_friendly_message_and_keeps_the_old_resume(self):
        self.profile.resume.save('mine.pdf', ContentFile(b'%PDF-1.4 uploaded by the student'), save=True)
        old_name = self.profile.resume.name
        with mock.patch.object(FileSystemStorage, 'save', side_effect=StorageUnavailable('down')):
            response = self.generate(confirm='1')
        self.assertContains(response, 'could not be saved right now')
        self.assertContains(response, 'Your entries are safe')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume.name, old_name)
        self.assertEqual(Education.objects.count(), 1)

    def test_builder_failure_does_not_become_a_server_error(self):
        with mock.patch('students.resume_views.generate_resume_pdf', side_effect=RuntimeError('boom')):
            response = self.generate(confirm='1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'could not be built')

    def test_preview_pdf_is_inline_private_and_not_saved(self):
        response = self.client.get(reverse('resume_preview_pdf'))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('inline', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.resume)

    def test_confirm_dialog_only_when_a_resume_exists(self):
        self.assertNotContains(self.client.get(reverse('resume_builder')), 'Replace your current resume?')
        self.profile.resume.save('mine.pdf', ContentFile(b'%PDF-1.4 x'), save=True)
        self.assertContains(self.client.get(reverse('resume_builder')), 'Replace your current resume?')


class PdfContentTests(TestCase):
    def full_data(self):
        user, profile = make_student('full', about='About me. ' * 80, skills=', '.join(f'Skill{i}' for i in range(60)),
                                     certifications='\n'.join(f'Cert {i}' for i in range(20)),
                                     linkedin='https://www.linkedin.com/in/asha?a=1&b=2')
        long_text = 'Built and shipped a feature used by thousands of students every single day. ' * 4
        for i in range(SECTION_LIMITS['education']):
            Education.objects.create(profile=profile, institution=f'College {i}', degree='B.Tech', position=i)
        for i in range(SECTION_LIMITS['experience']):
            Experience.objects.create(profile=profile, company=f'Company {i}', role='Intern', position=i,
                                      start_date=date(2025, 1, 1), end_date=date(2025, 3, 1),
                                      description='\n'.join([long_text] * 8))
        for i in range(SECTION_LIMITS['projects']):
            Project.objects.create(profile=profile, title=f'Project {i}', tech='Django', position=i,
                                   link='https://github.com/a/b', description='\n'.join([long_text] * 8))
        for i in range(SECTION_LIMITS['achievements']):
            Achievement.objects.create(profile=profile, text=long_text[:200], position=i)
        return build_resume(profile)

    def test_very_full_resume_paginates_and_stays_small(self):
        data = generate_resume_pdf(self.full_data())
        text, pages = pdf_text(data)
        self.assertGreater(pages, 1)
        self.assertLessEqual(pages, 5)
        self.assertLess(len(data), 2 * 1024 * 1024)
        self.assertIn('ACHIEVEMENTS', text)                                          # nothing was cut off

    def test_markup_characters_print_literally(self):
        user, profile = make_student('markup')
        profile.about = 'Loves <b>bold</b> & "quotes" <script>x</script>'
        profile.save()
        Education.objects.create(profile=profile, institution='A&M <University>', degree='B.Tech')
        text, _ = pdf_text(generate_resume_pdf(build_resume(profile)))
        self.assertIn('A&M <University>', text)
        self.assertIn('<b>bold</b> & "quotes"', text)

    def test_unprintable_characters_do_not_crash(self):
        user, profile = make_student('unicode')
        user.first_name = 'आशा'
        user.save()
        profile.about = 'Emoji 🎉 and Hindi हिन्दी'
        profile.save()
        Education.objects.create(profile=profile, institution='PEC', degree='B.Tech')
        data = generate_resume_pdf(build_resume(profile))
        self.assertTrue(data.startswith(b'%PDF-'))

    def test_long_unbroken_text_wraps_inside_the_page(self):
        user, profile = make_student('longword')
        Education.objects.create(profile=profile, institution='X' * 110, degree='B' * 90)
        Project.objects.create(profile=profile, title='P', link='https://example.com/' + 'a' * 300)
        data = generate_resume_pdf(build_resume(profile))
        reader = pypdf.PdfReader(io.BytesIO(data))
        width = float(reader.pages[0].mediabox.width)

        def check(text, cm, tm, font_dict, font_size):
            if text.strip():
                self.assertLess(tm[4], width)    # no text starts beyond the right edge
        reader.pages[0].extract_text(visitor_text=check)
        self.assertEqual(len(reader.pages), 1)
