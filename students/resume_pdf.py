"""Build the resume PDF with ReportLab.

One template: A4, single column, real selectable text, no tables, images or text boxes, so
applicant-tracking systems can read it. Only the standard Helvetica fonts are used, so the
file stays tiny and needs no font files on the server.

ReportLab treats '<' and '&' in a Paragraph as markup, so every piece of user text goes
through `esc()` before it is placed in a Paragraph.
"""
import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from .resume import short_link

INK = colors.HexColor('#111827')
MUTED = colors.HexColor('#4b5563')
RULE = colors.HexColor('#9ca3af')
LINK = colors.HexColor('#1d4ed8')

BODY = 9.5
_LONG_TOKEN = re.compile(r'\S{60,}')


def _soften(text):
    """A paragraph can only wrap at spaces; split absurdly long unbroken strings so they cannot overflow."""
    return _LONG_TOKEN.sub(lambda m: ' '.join(m.group(0)[i:i + 50] for i in range(0, len(m.group(0)), 50)), text)


def esc(text):
    """Make user text safe and printable: fit the standard font, wrap long words, escape markup."""
    text = (text or '').encode('cp1252', errors='replace').decode('cp1252')
    text = ''.join(ch if ch >= ' ' or ch == '\t' else ' ' for ch in text)
    return escape(_soften(text.strip()))


def _link(text, href):
    safe_href = escape(href, {'"': '&quot;'})
    return f'<link href="{safe_href}" color="#1d4ed8">{esc(text)}</link>'


def _styles():
    base = dict(fontName='Helvetica', fontSize=BODY, leading=BODY * 1.38, textColor=INK)
    return {
        'name': ParagraphStyle('name', **{**base, 'fontName': 'Helvetica-Bold', 'fontSize': 21, 'leading': 25}),
        'contact': ParagraphStyle('contact', **{**base, 'textColor': MUTED, 'spaceBefore': 3}),
        'heading': ParagraphStyle('heading', **{**base, 'fontName': 'Helvetica-Bold', 'fontSize': 10,
                                                'leading': 12, 'spaceBefore': 11, 'spaceAfter': 2}),
        'title': ParagraphStyle('title', **{**base, 'fontName': 'Helvetica-Bold', 'spaceBefore': 5}),
        'sub': ParagraphStyle('sub', **{**base, 'textColor': MUTED}),
        'text': ParagraphStyle('text', **base),
        'bullet': ParagraphStyle('bullet', **{**base, 'leftIndent': 12, 'bulletIndent': 2, 'spaceBefore': 1}),
    }


def _entry(item, st):
    """One entry as (keep, rest): the title lines plus the first bullet must share a page; later bullets may flow."""
    head = f'<b>{esc(item["title"])}</b>'
    if item['dates']:
        head += f'  |  {esc(item["dates"])}'
    parts = [Paragraph(head, st['title'])]
    sub = esc(item['sub']) if item['sub'] else ''
    if item['link']:
        sub = (sub + '  |  ' if sub else '') + _link(short_link(item['link'])[:70], item['link'])
    if sub:
        parts.append(Paragraph(sub, st['sub']))
    lines = [Paragraph(esc(line), st['bullet'], bulletText='\u2022') for line in item['bullets']]
    return parts + lines[:1], lines[1:]


def _bullets(lines, st):
    return [Paragraph(esc(line), st['bullet'], bulletText='\u2022') for line in lines]


def _section(title, entries, st):
    """entries = [(keep, rest), ...]. The heading rides with the first entry's `keep` so it is never
    stranded at the bottom of a page. (KeepTogether blocks are never nested: that breaks pagination.)"""
    story = []
    for i, (keep, rest) in enumerate(entries):
        if i == 0:
            keep = [Paragraph(title, st['heading']),
                    HRFlowable(width='100%', thickness=0.6, color=RULE, spaceBefore=0, spaceAfter=1)] + keep
        story.append(KeepTogether(keep))
        story.extend(rest)
    return story


def generate_resume_pdf(data):
    """Return the resume as PDF bytes. `data` comes from students.resume.build_resume()."""
    st = _styles()
    story = [Paragraph(esc(data['name']), st['name'])]

    if data['contact']:
        pieces = [_link(c['text'], c['href']) if c['href'] else esc(c['text']) for c in data['contact']]
        story.append(Paragraph('  |  '.join(pieces), st['contact']))

    if data['summary']:
        story += _section('SUMMARY', [([Paragraph(esc(data['summary']), st['text'])], [])], st)

    for key, title in (('education', 'EDUCATION'), ('experience', 'EXPERIENCE'), ('projects', 'PROJECTS')):
        if data[key]:
            story += _section(title, [_entry(item, st) for item in data[key]], st)

    if data['skills']:
        story += _section('SKILLS', [([Paragraph(esc(', '.join(data['skills'])), st['text'])], [])], st)
    if data['certifications']:
        lines = _bullets(data['certifications'], st)
        story += _section('CERTIFICATIONS', [(lines[:2], lines[2:])], st)
    if data['achievements']:
        lines = _bullets(data['achievements'], st)
        story += _section('ACHIEVEMENTS', [(lines[:2], lines[2:])], st)

    story.append(Spacer(1, 1))
    buffer = BytesIO()
    name = data['name'].encode('cp1252', errors='replace').decode('cp1252')
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=f'{name} - Resume', author=name, subject='Resume',
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )
    doc.build(story)
    return buffer.getvalue()
