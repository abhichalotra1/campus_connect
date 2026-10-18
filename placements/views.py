import json
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.decorators import verified_recruiter_required
from accounts.models import User 
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
import math

# ── MODELS IMPORT ──
from .models import PlacementDrive, Application, Interview, Bookmark
from students.models import StudentProfile
from students.validators import validate_image_size
from notifications.views import send_notification
from campus_connect.email_utils import (
    send_application_email,
    send_recruiter_email,
    send_interview_email,
    send_withdrawal_email,
    send_status_update_email,
)


# ══════════════════════════════════════════════════════════════
# DRIVE & APPLICATION VIEWS
# ══════════════════════════════════════════════════════════════

@login_required
def drive_list_view(request):
    from .utils import close_expired_drives
    close_expired_drives()
    drives = PlacementDrive.objects.filter(status='active').order_by('-created_at')

    search   = request.GET.get('search', '')
    branch   = request.GET.get('branch', '')
    job_type = request.GET.get('job_type', '')

    if search:
        drives = (drives.filter(company__icontains=search) | drives.filter(role__icontains=search)).distinct()
    if branch:
        drives = drives.filter(eligible_branch=branch)
    if job_type:
        drives = drives.filter(job_type=job_type)

    applied_ids = []
    bookmarked_ids = [] 
    if request.user.role == 'student':
        applied_ids = Application.objects.filter(student=request.user).values_list('drive_id', flat=True)
        bookmarked_ids = Bookmark.objects.filter(student=request.user).values_list('drive_id', flat=True)

    return render(request, 'placements/drive_list.html', {
        'drives':      drives,
        'applied_ids': applied_ids,
        'search':      search,
        'bookmarked_ids': bookmarked_ids,
        'branch':      branch,
        'job_type':    job_type,
    })


@login_required
def drive_detail_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)
    already_applied = Application.objects.filter(student=request.user, drive=drive).exists()

    is_saved = False
    if request.user.role == 'student':
        is_saved = Bookmark.objects.filter(student=request.user, drive=drive).exists()

    return render(request, 'placements/drive_detail.html', {
        'drive':           drive,
        'already_applied': already_applied,
        'is_saved':        is_saved,
    })


@login_required
@require_POST
def apply_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.user.role != 'student':
        messages.error(request, 'Only students can apply to drives.')
        return redirect('drive_detail', pk=pk)

    if drive.deadline < timezone.now().date():
        messages.error(request, 'The deadline for this drive has passed!')
        return redirect('drive_detail', pk=pk)

    if drive.status == 'closed':
        messages.error(request, 'This drive is no longer accepting applications!')
        return redirect('drive_detail', pk=pk)

    try:
        profile = StudentProfile.objects.get(user=request.user)
        if profile.cgpa < drive.min_cgpa:
            messages.error(request, f'You need minimum {drive.min_cgpa} CGPA to apply!')
            return redirect('drive_detail', pk=pk)
        if drive.eligible_branch != 'ALL' and profile.branch != drive.eligible_branch:
            messages.error(request, 'Your branch is not eligible for this drive!')
            return redirect('drive_detail', pk=pk)
    except StudentProfile.DoesNotExist:
        messages.error(request, 'Please complete your profile before applying!')
        return redirect('edit_profile')

    if Application.objects.filter(student=request.user, drive=drive).exists():
        messages.warning(request, 'You have already applied for this drive!')
        return redirect('drive_list')

    Application.objects.create(student=request.user, drive=drive)

    send_notification(
        user=request.user,
        title=f'Applied to {drive.company}',
        message=f'You have successfully applied for {drive.role} at {drive.company}. Good luck!',
        notif_type='general'
    )

    send_application_email(request.user, drive)
    send_recruiter_email(drive.posted_by, request.user, drive)

    messages.success(request, f'Successfully applied to {drive.company}!')
    return redirect('my_applications')


@login_required
def my_applications_view(request):
    applications = Application.objects.filter(student=request.user).order_by('-applied_at')
    return render(request, 'placements/my_applications.html', {
        'applications': applications
    })


@login_required
def withdraw_view(request, pk):
    application = get_object_or_404(Application, pk=pk, student=request.user)

    if application.status != 'applied':
        messages.error(request, 'You cannot withdraw an application that has already been shortlisted/selected!')
        return redirect('my_applications')

    if request.method == 'POST':
        drive   = application.drive
        student = request.user

        send_withdrawal_email(student, drive)

        application.delete()
        messages.success(request, f'Application for {drive.company} withdrawn successfully.')
        return redirect('my_applications')

    return render(request, 'placements/withdraw_confirm.html', {'application': application})


@login_required
def post_drive_view(request):
    if request.user.role == 'recruiter':
        try:
            if not request.user.recruiterprofile.is_verified:
                messages.error(request, 'You must be a verified recruiter to post drives.')
                return redirect('verification_status')
        except Exception:
            return redirect('verification_status')
    elif request.user.role != 'admin':
        messages.error(request, 'Only recruiters can post jobs!')
        return redirect('drive_list')

    if request.method == 'POST':
        drive, errors = _build_drive_from_post(request)
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'placements/post_drive.html')
        drive.save()
        messages.success(request, 'Placement drive posted successfully!')
        return redirect('recruiter_dashboard')

    return render(request, 'placements/post_drive.html')


def _parse_finite_float(raw):
    """Return a finite float, or None if raw is not one (rejects 'nan'/'inf')."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _build_drive_from_post(request):
    """Validate the post-drive form. Returns (unsaved PlacementDrive, [error strings])."""
    post = request.POST
    errors = []

    text = {name: post.get(name, '').strip() for name in ('company', 'role', 'description', 'location')}
    skills = post.get('skills_required', '').strip()
    job_type = post.get('job_type', '')
    branch = post.get('eligible_branch', '')
    salary_type = post.get('salary_type', '')

    min_cgpa = _parse_finite_float(post.get('min_cgpa', '0') or '0')
    if min_cgpa is None or not 0 <= min_cgpa <= 10:
        errors.append('Minimum CGPA must be a number between 0 and 10.')
        min_cgpa = 0.0

    raw_salary = post.get('salary_amount', '').strip()
    if salary_type == 'not_disclosed' and raw_salary == '':
        salary = 0.0  # keeps formatted_salary showing "Not Disclosed"
    else:
        salary = _parse_finite_float(raw_salary)
        if salary is None or salary < 0:
            errors.append('Enter a valid salary amount (0 or more).')
            salary = 0.0

    deadline = None
    raw_deadline = post.get('deadline', '').strip()
    try:
        deadline = parse_date(raw_deadline)  # None if wrong format, ValueError if impossible date
    except ValueError:
        deadline = None
    if deadline is None:
        errors.append('Enter a valid application deadline.')
    elif deadline < timezone.now().date():
        errors.append('The deadline cannot be in the past.')

    logo = request.FILES.get('company_logo')
    if logo is None:
        errors.append('Company Logo is compulsory!')

    drive = PlacementDrive(
        posted_by=request.user, company_logo=logo, salary_amount=salary, salary_type=salary_type,
        job_type=job_type, eligible_branch=branch, min_cgpa=min_cgpa, skills_required=skills,
        deadline=deadline, **text,
    )

    # Let the model check required text, lengths and the choice fields. Fields already
    # reported above are excluded so the user doesn't see the same problem twice.
    exclude = ['posted_by', 'min_cgpa', 'salary_amount', 'deadline', 'company_logo', 'status']
    try:
        drive.full_clean(exclude=exclude)
    except ValidationError as exc:
        for field, msgs in exc.message_dict.items():
            label = PlacementDrive._meta.get_field(field).verbose_name.capitalize() if field != '__all__' else ''
            for msg in msgs:
                errors.append(f'{label}: {msg}' if label else msg)

    if logo is not None:
        try:
            validate_image_size(logo)
        except ValidationError as exc:
            errors.extend(exc.messages)

    return drive, errors


@login_required
def my_interviews_view(request):
    now = timezone.now()
    
    # 1. Upcoming interviews: scheduled_at is greater than or equal to right now
    upcoming_interviews = Interview.objects.filter(
        application__student=request.user, 
        scheduled_at__gte=now
    ).order_by('scheduled_at')

    # 2. Past interviews: scheduled_at is less than right now
    past_interviews = Interview.objects.filter(
        application__student=request.user, 
        scheduled_at__lt=now
    ).order_by('-scheduled_at')

    return render(request, 'placements/my_interviews.html', {
        'upcoming_interviews': upcoming_interviews,
        'past_interviews': past_interviews
    })    


@login_required
def schedule_interview_view(request, app_id):
    if request.user.role not in ['admin', 'recruiter']:
        messages.error(request, 'Access denied!')
        return redirect('dashboard')

    application = get_object_or_404(Application.objects.select_related('drive'), pk=app_id)

    # Recruiters may only schedule interviews for applicants to their own drives
    if request.user.role != 'admin' and application.drive.posted_by != request.user:
        messages.error(request, "You can only schedule interviews for your own drives.")
        return redirect('recruiter_applicants')

    if request.method == 'POST':
        location     = request.POST.get('location', '').strip()
        meeting_link = request.POST.get('meeting_link', '').strip()
        notes        = request.POST.get('notes', '').strip()

        try:
            scheduled_at = parse_datetime(request.POST.get('scheduled_at', '').strip())
        except ValueError:
            scheduled_at = None

        error = None
        if scheduled_at is None:
            error = 'Please choose a valid interview date and time.'
        else:
            if timezone.is_naive(scheduled_at):
                scheduled_at = timezone.make_aware(scheduled_at)
            if scheduled_at <= timezone.now():
                error = 'The interview time must be in the future.'

        if error is None:
            interview = Interview(application=application, scheduled_at=scheduled_at, location=location,
                                  meeting_link=meeting_link, notes=notes, status='scheduled')
            try:
                interview.full_clean(exclude=['application'])
            except ValidationError as exc:
                error = ' '.join(f'{f.replace("_", " ").title()}: {m}'
                                 for f, msgs in exc.message_dict.items() for m in msgs)

        if error:
            messages.error(request, error)
            return render(request, 'placements/schedule_interview.html', {'application': application})

        Interview.objects.update_or_create(
            application=application,
            defaults={
                'scheduled_at': scheduled_at,
                'location':     location,
                'meeting_link': meeting_link,
                'notes':        notes,
                'status':       'scheduled',
            }
        )

        when = timezone.localtime(scheduled_at).strftime('%d %b %Y, %I:%M %p')
        send_notification(
            user=application.student,
            title=f'Interview Scheduled - {application.drive.company}',
            message=f'Your interview for {application.drive.role} at {application.drive.company} is scheduled on {when}.',
            notif_type='general'
        )

        send_interview_email(
            student=application.student,
            drive=application.drive,
            scheduled_at=when,
            location=location,
            meeting_link=meeting_link,
            notes=notes,
        )

        messages.success(request, 'Interview scheduled successfully!')
        if request.user.role == 'admin':
            return redirect('admin_dashboard')
        return redirect(f"{reverse('recruiter_applicants')}?drive={application.drive_id}")

    return render(request, 'placements/schedule_interview.html', {
        'application': application
    })


@login_required
def recruiter_applicants_view(request):
    if request.user.role not in ['recruiter', 'admin']:
        return redirect('drive_list')

    # Admins can review applicants for every drive; recruiters only their own
    if request.user.role == 'admin':
        my_drives = PlacementDrive.objects.all().order_by('-created_at')
    else:
        my_drives = PlacementDrive.objects.filter(posted_by=request.user).order_by('-created_at')
    selected_drive_id = request.GET.get('drive')
    applications      = []
    selected_drive    = None

    if selected_drive_id:
        selected_drive = get_object_or_404(my_drives, pk=selected_drive_id)
        applications   = Application.objects.filter(drive=selected_drive).select_related('student', 'student__studentprofile')

    return render(request, 'placements/recruiter_applicants.html', {
        'drives':         my_drives,
        'applications':   applications,
        'selected_drive': selected_drive,
        'status_choices': Application.STATUS_CHOICES,
    })


@login_required
def recruiter_dashboard_view(request):
    if request.user.role != 'recruiter':
        messages.error(request, "Access denied!")
        return redirect('dashboard')

    my_drives = PlacementDrive.objects.filter(posted_by=request.user).order_by('-created_at')

    return render(request, 'placements/recruiter_dashboard.html', {
        'my_drives': my_drives
    })


@login_required
def edit_drive_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.user.role != 'admin' and drive.posted_by != request.user:
        messages.error(request, "You don't have permission to edit this drive!")
        return redirect('drive_list')

    if request.method == 'POST':
        drive.company         = request.POST.get('company', drive.company)
        drive.role            = request.POST.get('role', drive.role)
        drive.description     = request.POST.get('description', drive.description)
        drive.location        = request.POST.get('location', drive.location)

        try:
            drive.salary_amount = float(request.POST.get('salary_amount', drive.salary_amount))
        except (ValueError, TypeError):
            pass

        drive.salary_type     = request.POST.get('salary_type', drive.salary_type)
        drive.job_type        = request.POST.get('job_type', drive.job_type)
        drive.eligible_branch = request.POST.get('eligible_branch', drive.eligible_branch)
        drive.skills_required = request.POST.get('skills_required', drive.skills_required)
        drive.deadline        = request.POST.get('deadline', drive.deadline)

        try:
            drive.min_cgpa = float(request.POST.get('min_cgpa', drive.min_cgpa))
        except (ValueError, TypeError):
            pass

        if 'company_logo' in request.FILES:
            drive.company_logo = request.FILES['company_logo']

        drive.save()
        messages.success(request, f'Drive "{drive.role}" updated successfully!')
        return redirect('recruiter_dashboard')

    return render(request, 'placements/edit_drive.html', {'drive': drive})


@login_required
def delete_drive_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.user.role != 'admin' and drive.posted_by != request.user:
        messages.error(request, "You don't have permission to delete this drive!")
        return redirect('drive_list')

    if request.method == 'POST':
        drive.delete()
        messages.success(request, f'Drive "{drive.role}" has been deleted.')
        return redirect('recruiter_dashboard')

    return render(request, 'placements/delete_drive_confirm.html', {'drive': drive})


@login_required
def saved_jobs_view(request):
    if request.user.role != 'student':
        messages.error(request, 'Access denied!')
        return redirect('dashboard')
    
    bookmarks = Bookmark.objects.filter(student=request.user).select_related('drive').order_by('-saved_at')
    applied_ids = Application.objects.filter(student=request.user).values_list('drive_id', flat=True)
    
    return render(request, 'placements/saved_jobs.html', {
        'bookmarks': bookmarks,
        'applied_ids': applied_ids
    })

@login_required
@require_POST
def save_drive_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)
    
    if request.user.role != 'student':
        messages.error(request, 'Only students can save jobs.')
        return redirect('drive_detail', pk=pk)
        
    bookmark, created = Bookmark.objects.get_or_create(student=request.user, drive=drive)
    
    if created:
        messages.success(request, f'Job at {drive.company} saved to your list!')
    else:
        messages.info(request, 'You have already saved this job.')
        
    return redirect('drive_detail', pk=pk)

@login_required
@require_POST
def unsave_drive_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)
    
    if request.user.role != 'student':
        return redirect('drive_detail', pk=pk)
        
    bookmark = Bookmark.objects.filter(student=request.user, drive=drive)
    if bookmark.exists():
        bookmark.delete()
        messages.success(request, f'Job at {drive.company} removed from your saved list.')
    else:
        messages.info(request, 'This job was not in your saved list.')
        
    referer = request.META.get('HTTP_REFERER', '')
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(referer)
    return redirect('saved_jobs')