from django.test import TestCase
from django.urls import reverse

from accounts.models import User

PW = 'Pass12345!x'


def _login(client, username, role):
    u = User.objects.create_user(username=username, email=f'{username}@example.com', password=PW, role=role)
    client.force_login(u)
    return u


class DashboardCardTests(TestCase):
    def html(self, role):
        _login(self.client, f'c_{role}', role)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn('{#', html)
        self.assertEqual(html.count('class="sc anim'), 4)
        return html

    def test_student_cards_link_to_student_pages(self):
        html = self.html('student')
        for name in ('drive_list', 'my_applications', 'my_interviews'):
            self.assertIn(f'href="{reverse(name)}"', html)

    def test_recruiter_cards_link_to_recruiter_pages(self):
        html = self.html('recruiter')
        self.assertIn(f'href="{reverse("recruiter_dashboard")}"', html)
        self.assertIn(f'href="{reverse("recruiter_applicants")}"', html)

    def test_admin_cards_link_to_admin_tabs(self):
        html = self.html('admin')
        base = reverse('admin_dashboard')
        for tab in ('drives', 'applications', 'students'):
            self.assertIn(f'{base}?tab={tab}', html)
        self.assertIn('status=shortlisted', html)

    def test_counts_render(self):
        u = _login(self.client, 'cnt', 'admin')
        for i in range(3):
            User.objects.create_user(username=f'st{i}', password=PW, role='student')
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('data-count="3"', html)
