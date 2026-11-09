from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.notify import notify_admins
from campus_connect.forms_util import flash_form_errors
from campus_connect.pagination import paginate
from notifications.views import send_notification
from students.models import StudentProfile
from .forms import PlacementDriveForm
from .models import PlacementDrive, Application, Interview, Bookmark
from campus_connect.email_utils import (
    send_application_email,
    send_recruiter_email,
    send_interview_email,
    send_withdrawal_email,
)


# ══════════════════════════════════════════════════════════════
# DRIVE & APPLICATION VIEWS
# ══════════════════════════════════════════════════════════════

@login_required
def drive_list_view(request):
    drives = PlacementDrive.objects.open().order_by('-created_at')

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

    page, page_query = paginate(request, drives, per_page=12)

    return render(request, 'placements/drive_list.html', {
        'drives':      page,
        'page_obj':    page,
        'page_query':  page_query,
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
    missing_fields = []
    if request.user.role == 'student':
        is_saved = Bookmark.objects.filter(student=request.user, drive=drive).exists()
        profile = StudentProfile.objects.filter(user=request.user).first() or StudentProfile(user=request.user)
        missing_fields = profile.missing_required_fields()

    return render(request, 'placements/drive_detail.html', {
        'drive':           drive,
        'already_applied': already_applied,
        'is_saved':        is_saved,
        'missing_fields':  missing_fields,
    })


@login_required
@require_POST
def apply_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.user.role != 'student':
        messages.error(request, 'Only students can apply to drives.')
        return redirect('drive_detail', pk=pk)

    if drive.deadline < timezone.localdate():
        messages.error(request, 'The deadline for this drive has passed!')
        return redirect('drive_detail', pk=pk)

    if drive.status == 'closed':
        messages.error(request, 'This drive is no longer accepting applications!')
        return redirect('drive_detail', pk=pk)

    # A student must have the basics filled in before applying (no profile at all counts as empty)
    profile = StudentProfile.objects.filter(user=request.user).first() or StudentProfile(user=request.user)
    missing = profile.missing_required_fields()
    if missing:
        messages.error(request, 'Complete your profile before applying. Still needed: ' + ', '.join(missing) + '.')
        return redirect('edit_profile')

    if profile.cgpa < drive.min_cgpa:
        messages.error(request, f'You need minimum {drive.min_cgpa} CGPA to apply!')
        return redirect('drive_detail', pk=pk)
    if drive.eligible_branch != 'ALL' and profile.branch != drive.eligible_branch:
        messages.error(request, 'Your branch is not eligible for this drive!')
        return redirect('drive_detail', pk=pk)

    if Application.objects.filter(student=request.user, drive=drive).exists():
        messages.warning(request, 'You have already applied for this drive!')
        return redirect('drive_list')

    try:
        with transaction.atomic():
            Application.objects.create(student=request.user, drive=drive)
    except IntegrityError:
        # Double-click / two tabs: the other request already created it.
        messages.warning(request, 'You have already applied for this drive!')
        return redirect('drive_list')

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
    applications, page_query = paginate(
        request, Application.objects.filter(student=request.user).order_by('-applied_at'), per_page=10)
    return render(request, 'placements/my_applications.html', {
        'page_obj': applications, 'page_query': page_query,
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


def _after_drive_change(request):
    """Where to go after posting, editing or deleting a drive: admins land on their Drives tab."""
    if request.user.role == 'admin':
        return redirect(f"{reverse('admin_dashboard')}?tab=drives")
    return redirect('recruiter_dashboard')


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
        form = PlacementDriveForm(request.POST, request.FILES)
        if not form.is_valid():
            flash_form_errors(request, form)
            # Hand back what was typed (the logo can't be re-filled by a browser)
            return render(request, 'placements/post_drive.html', {'v': request.POST})
        drive = form.save(commit=False)
        drive.posted_by = request.user
        drive.save()
        if request.user.role == 'recruiter':
            notify_admins('New drive posted',
                          f'{request.user.username} posted "{drive.role}" at {drive.company}.')
        log_action(request, 'drive_posted', f'{drive.company} - {drive.role}',
                   f'Drive #{drive.pk} posted by {request.user.role} {request.user.username}')
        messages.success(request, 'Placement drive posted successfully!')
        return _after_drive_change(request)

    return render(request, 'placements/post_drive.html')


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
        applications   = Application.objects.filter(drive=selected_drive).select_related(
            'student', 'student__studentprofile').order_by('-applied_at')

    total_applicants = len(applications) if isinstance(applications, list) else applications.count()
    page, page_query = (paginate(request, applications, per_page=20) if selected_drive else (applications, ''))

    return render(request, 'placements/recruiter_applicants.html', {
        'drives':         my_drives,
        'applications':   page,
        'page_obj':       page if selected_drive else None,
        'page_query':     page_query,
        'total_applicants': total_applicants,
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
        form = PlacementDriveForm(request.POST, request.FILES, instance=drive)
        if not form.is_valid():
            flash_form_errors(request, form)
            # `drive` now holds the valid edits made so far; nothing has been saved
            return render(request, 'placements/edit_drive.html', {'drive': drive})
        drive = form.save()
        messages.success(request, f'Drive "{drive.role}" updated successfully!')
        return _after_drive_change(request)

    return render(request, 'placements/edit_drive.html', {'drive': drive})


@login_required
def delete_drive_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.user.role != 'admin' and drive.posted_by != request.user:
        messages.error(request, "You don't have permission to delete this drive!")
        return redirect('drive_list')

    app_count = Application.objects.filter(drive=drive).count()

    if request.method == 'POST':
        if app_count:
            messages.error(
                request, f'"{drive.role}" has {app_count} application(s) and cannot be deleted. '
                         'Close the drive instead to stop new applications.')
            return _after_drive_change(request)
        label = f'{drive.company} - {drive.role}'
        pk = drive.pk
        drive.delete()
        log_action(request, 'drive_deleted', label, f'Drive #{pk} deleted')
        messages.success(request, f'Drive "{drive.role}" has been deleted.')
        return _after_drive_change(request)

    return render(request, 'placements/delete_drive_confirm.html', {'drive': drive, 'app_count': app_count})


@login_required
def saved_jobs_view(request):
    if request.user.role != 'student':
        messages.error(request, 'Access denied!')
        return redirect('dashboard')
    
    bookmarks, page_query = paginate(
        request, Bookmark.objects.filter(student=request.user).select_related('drive').order_by('-saved_at'), per_page=12)
    applied_ids = Application.objects.filter(student=request.user).values_list('drive_id', flat=True)
    
    return render(request, 'placements/saved_jobs.html', {
        'bookmarks': bookmarks,
        'page_obj': bookmarks,
        'page_query': page_query,
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