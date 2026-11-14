"""Resume Builder: entries, preview, and generating the PDF into the student's profile."""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from campus_connect.storage import StorageUnavailable
from .models import StudentProfile
from .resume import (SECTION_LIMITS, achievement_item, build_resume, education_item,
                     experience_item, project_item)
from .resume_forms import AchievementForm, EducationForm, ExperienceForm, ProjectForm
from .resume_pdf import generate_resume_pdf
from .validators import validate_resume

logger = logging.getLogger(__name__)

# Everything that differs between the four sections lives here.
SECTIONS = {
    'education': {
        'label': 'Education', 'singular': 'education', 'icon': 'fa-graduation-cap', 'related': 'educations',
        'form': EducationForm, 'item': education_item,
        'hint': 'Your degree and school. Add class 12 too if you want it on the resume.',
        'empty': 'Add your degree to start the resume.',
    },
    'experience': {
        'label': 'Experience', 'singular': 'experience', 'icon': 'fa-briefcase', 'related': 'experiences',
        'form': ExperienceForm, 'item': experience_item,
        'hint': 'Internships, part-time work and freelance jobs.',
        'empty': 'No internships yet? Projects below can carry the resume.',
    },
    'projects': {
        'label': 'Projects', 'singular': 'project', 'icon': 'fa-code', 'related': 'projects',
        'form': ProjectForm, 'item': project_item,
        'hint': 'Things you built, with the tools you used.',
        'empty': 'Add a project you are proud of.',
    },
    'achievements': {
        'label': 'Achievements', 'singular': 'achievement', 'icon': 'fa-trophy', 'related': 'achievements',
        'form': AchievementForm, 'item': achievement_item,
        'hint': 'Awards, rankings, hackathons and leadership roles.',
        'empty': 'Add a win, a rank or a role you held.',
    },
}


def student_required(view):
    """Resume Builder is for students only; everyone else is sent back to the dashboard."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'student':
            messages.error(request, 'Access denied. Resume Builder is for students.')
            return redirect('dashboard')
        return view(request, *args, **kwargs)
    return wrapper


def _config(kind):
    config = SECTIONS.get(kind)
    if config is None:
        raise Http404
    return config


def _manager(profile, kind):
    return getattr(profile, SECTIONS[kind]['related'])


def _back(kind=None):
    url = reverse('resume_builder')
    return redirect(f'{url}#{kind}' if kind else url)


def _auto_id(kind, pk=None):
    """Unique element ids per form, because the add form and an edit form can share one page."""
    return f'{"edit" if pk else "add"}_{kind}_{pk or 0}_%s'


def _education_initial(profile):
    """The first education entry starts from what the profile already knows."""
    initial = {'degree': 'B.Tech'}
    if profile.branch:
        initial['field_of_study'] = dict(StudentProfile.BRANCH_CHOICES).get(profile.branch, '')
    if profile.passing_year:
        initial['end_year'] = profile.passing_year
    if profile.cgpa:
        initial['grade'] = f'{profile.cgpa:g} CGPA'
    return initial


def _render_builder(request, profile, bound=None):
    """Render the builder page. `bound` = (kind, pk or None, form) re-opens a form with its errors."""
    edit_kind = edit_pk = None
    if bound:
        edit_kind, edit_pk, _ = bound
    else:
        wanted = request.GET.get('edit', '')
        kind, _, pk = wanted.rpartition('-')
        if kind in SECTIONS and pk.isdigit():
            edit_kind, edit_pk = kind, int(pk)

    sections = []
    for kind, config in SECTIONS.items():
        entries = list(_manager(profile, kind).all())
        rows = []
        for entry in entries:
            row = config['item'](entry)
            row['editing'] = (kind == edit_kind and entry.pk == edit_pk)
            if row['editing']:
                row['form'] = bound[2] if bound else config['form'](instance=entry, auto_id=_auto_id(kind, entry.pk))
            rows.append(row)
        if edit_kind == kind and not any(r['editing'] for r in rows) and edit_pk is not None:
            edit_kind = edit_pk = None   # stale ?edit= link: ignore it
        limit = SECTION_LIMITS[kind]
        add_is_bound = bool(bound and bound[0] == kind and bound[1] is None)
        if add_is_bound:
            add_form = bound[2]
        else:
            initial = _education_initial(profile) if kind == 'education' and not entries else None
            add_form = config['form'](initial=initial, auto_id=_auto_id(kind))
        sections.append({
            'kind': kind, 'label': config['label'], 'singular': config['singular'], 'icon': config['icon'],
            'hint': config['hint'], 'empty': config['empty'], 'rows': rows, 'count': len(rows), 'limit': limit,
            'at_limit': len(rows) >= limit, 'add_form': add_form, 'add_open': add_is_bound,
        })

    resume = build_resume(profile)
    user = request.user
    profile_gaps = []
    if not user.phone:
        profile_gaps.append('phone number')
    if not profile.skills.strip():
        profile_gaps.append('skills')
    if not profile.about.strip():
        profile_gaps.append('about')

    return render(request, 'students/resume_builder.html', {
        'profile': profile, 'resume': resume, 'sections': sections,
        'profile_gaps': profile_gaps, 'can_generate': resume['has_content'],
    })


@student_required
def resume_builder_view(request):
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    return _render_builder(request, profile)


@student_required
@require_POST
def resume_entry_save_view(request, kind, pk=None):
    config = _config(kind)
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    manager = _manager(profile, kind)
    instance = get_object_or_404(manager, pk=pk) if pk else None   # scoped to this student's own rows

    if instance is None and manager.count() >= SECTION_LIMITS[kind]:
        messages.error(request, f'You can add up to {SECTION_LIMITS[kind]} {config["label"].lower()} entries. '
                                'Delete one to add another.')
        return _back(kind)

    form = config['form'](request.POST, instance=instance, auto_id=_auto_id(kind, pk))
    if not form.is_valid():
        return _render_builder(request, profile, bound=(kind, pk, form))   # errors show inline

    entry = form.save(commit=False)
    entry.profile = profile
    if instance is None:
        entry.position = (manager.aggregate(top=Max('position'))['top'] or 0) + 1
    entry.save()
    messages.success(request, f'{config["singular"].capitalize()} {"updated" if instance else "added"}.')
    return _back(kind)


@student_required
@require_POST
def resume_entry_delete_view(request, kind, pk):
    _config(kind)
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    get_object_or_404(_manager(profile, kind), pk=pk).delete()
    messages.success(request, 'Entry deleted.')
    return _back(kind)


@student_required
@require_POST
def resume_entry_move_view(request, kind, pk, direction):
    _config(kind)
    if direction not in ('up', 'down'):
        raise Http404
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    entries = list(_manager(profile, kind).all())
    index = next((i for i, e in enumerate(entries) if e.pk == pk), None)
    if index is None:
        raise Http404
    target = index - 1 if direction == 'up' else index + 1
    if 0 <= target < len(entries):
        entries[index], entries[target] = entries[target], entries[index]
        with transaction.atomic():
            for position, entry in enumerate(entries):   # renumber so equal positions can never tie
                if entry.position != position:
                    entry.position = position
                    entry.save(update_fields=['position'])
    return _back(kind)


@student_required
@require_GET
def resume_preview_pdf_view(request):
    """Show the PDF without saving it anywhere."""
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    data = build_resume(profile)
    if not data['has_content']:
        messages.error(request, 'Add an education, experience or project entry to preview the PDF.')
        return _back()
    response = HttpResponse(generate_resume_pdf(data), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="resume-preview.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response


@student_required
@require_POST
def resume_generate_view(request):
    """Build the PDF and save it as the student's resume (the same field an upload fills)."""
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    data = build_resume(profile)
    if not data['has_content']:
        messages.error(request, 'Add an education, experience or project entry before generating.')
        return _back()
    if profile.resume and request.POST.get('confirm') != '1':
        messages.error(request, 'You already have a resume on file. Confirm that you want to replace it.')
        return _back()

    try:
        pdf = generate_resume_pdf(data)
    except Exception:   # a bad entry must not turn into a server error page
        logger.exception('Resume PDF generation failed for user %s', request.user.pk)
        messages.error(request, 'The PDF could not be built. Check your entries for unusual characters and try again.')
        return _back()

    upload = ContentFile(pdf, name='resume.pdf')
    try:
        validate_resume(upload)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return _back()

    try:
        profile.resume.save('resume.pdf', upload, save=False)
        profile.save(update_fields=['resume', 'updated_at'])   # old file is cleaned up by file_cleanup
    except StorageUnavailable:
        messages.error(request, 'Your resume was built but could not be saved right now. '
                                'Your entries are safe. Please try again in a minute.')
        return _back()

    messages.success(request, 'Resume generated and saved to your profile. You can apply to drives with it now.')
    return _back()
