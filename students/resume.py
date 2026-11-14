"""Turn a student's profile and resume entries into one plain dict.

The on-screen preview (templates/students/_resume_sheet.html) and the PDF
(students/resume_pdf.py) both read this dict, so what the student sees is what gets printed.
"""
import re

# Most entries a student can add per section. Keeps the resume to a sensible length and the
# PDF far below the 2 MB upload limit.
SECTION_LIMITS = {'education': 4, 'experience': 6, 'projects': 6, 'achievements': 8}

MAX_BULLETS = 6          # bullet points shown per entry
MAX_BULLET_CHARS = 220
MAX_SUMMARY_CHARS = 600
MAX_SKILLS = 30
MAX_CERTIFICATIONS = 8

_BULLET_PREFIX = re.compile(r'^[\s\-\u2022*\u00b7]+')


def clip(text, limit):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'


def bullets(text):
    """One bullet per non-empty line; a leading '-', '*' or bullet sign is ignored."""
    lines = []
    for raw in (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = _BULLET_PREFIX.sub('', raw).strip()
        if line:
            lines.append(clip(line, MAX_BULLET_CHARS))
    return lines[:MAX_BULLETS]


def split_items(text, limit):
    """Split a free-text profile field into a de-duplicated list (one item per line or comma)."""
    text = (text or '').replace('\r\n', '\n')
    parts = text.split('\n') if '\n' in text.strip() else text.split(',')
    seen, items = set(), []
    for part in parts:
        part = part.strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            items.append(clip(part, 80))
    return items[:limit]


def month_year(day):
    return day.strftime('%b %Y')


def date_range(start, end, current=False):
    if not start:
        return ''
    finish = 'Present' if current else (end or '')
    if not finish or finish == start:
        return str(start)
    return f'{start} \u2013 {finish}'


def short_link(url):
    return re.sub(r'^https?://(www\.)?', '', url or '').rstrip('/')


def education_item(entry):
    degree = ', '.join(part for part in (entry.degree, entry.field_of_study) if part)
    sub = ' \u00b7 '.join(part for part in (degree, entry.grade) if part)
    return {
        'pk': entry.pk, 'title': entry.institution, 'sub': sub,
        'dates': date_range(entry.start_year, entry.end_year), 'bullets': [], 'link': '',
    }


def experience_item(entry):
    return {
        'pk': entry.pk, 'title': entry.role, 'sub': entry.company,
        'dates': date_range(month_year(entry.start_date),
                            month_year(entry.end_date) if entry.end_date else '', entry.is_current),
        'bullets': bullets(entry.description), 'link': '',
    }


def project_item(entry):
    return {
        'pk': entry.pk, 'title': entry.title, 'sub': entry.tech, 'dates': '',
        'bullets': bullets(entry.description), 'link': entry.link,
    }


def achievement_item(entry):
    return {'pk': entry.pk, 'title': entry.text, 'sub': '', 'dates': '', 'bullets': [], 'link': ''}


def build_resume(profile):
    """Everything that goes on the resume, ready to render."""
    user = profile.user
    contact = []
    if user.email:
        contact.append({'text': user.email, 'href': f'mailto:{user.email}'})
    if user.phone:
        contact.append({'text': user.phone, 'href': ''})
    if profile.linkedin:
        contact.append({'text': short_link(profile.linkedin), 'href': profile.linkedin})
    if profile.github:
        contact.append({'text': short_link(profile.github), 'href': profile.github})

    data = {
        'name': user.get_full_name().strip() or user.username,
        'contact': contact,
        'summary': clip(profile.about, MAX_SUMMARY_CHARS),
        'education': [education_item(e) for e in profile.educations.all()],
        'experience': [experience_item(e) for e in profile.experiences.all()],
        'projects': [project_item(e) for e in profile.projects.all()],
        'skills': split_items(profile.skills, MAX_SKILLS),
        'certifications': split_items(profile.certifications, MAX_CERTIFICATIONS),
        'achievements': [a.text for a in profile.achievements.all()],
    }
    # The PDF needs something real to show before it is worth generating.
    data['has_content'] = bool(data['education'] or data['experience'] or data['projects'])
    return data
