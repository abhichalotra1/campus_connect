from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import PlacementDrive, Application, Interview
from students.models import StudentProfile
from notifications.views import send_notification
from campus_connect.email_utils import (
    send_application_email,
    send_recruiter_email,
    send_interview_email
)

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
    if request.user.role == 'student':
        applied_ids = Application.objects.filter(
            student=request.user
        ).values_list('drive_id', flat=True)

    return render(request, 'placements/drive_list.html', {
        'drives':      drives,
        'applied_ids': applied_ids,
        'search':      search,
        'branch':      branch,
        'job_type':    job_type,
    })


@login_required
def drive_detail_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)
    already_applied = Application.objects.filter(
        student=request.user, drive=drive
    ).exists()

    return render(request, 'placements/drive_detail.html', {
        'drive':           drive,
        'already_applied': already_applied,
    })


@login_required
def apply_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

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

    # Send portal notification to student
    send_notification(
        user=request.user,
        title=f'Applied to {drive.company}',
        message=f'You have successfully applied for {drive.role} at {drive.company}. Good luck!',
        notif_type='general'
    )

    # Send email to student
    send_application_email(request.user, drive)

    # Send email to recruiter
    send_recruiter_email(drive.posted_by, request.user, drive)

    messages.success(request, f'Successfully applied to {drive.company}!')
    return redirect('my_applications')


@login_required
def my_applications_view(request):
    applications = Application.objects.filter(
        student=request.user
    ).order_by('-applied_at')
    return render(request, 'placements/my_applications.html', {
        'applications': applications
    })


@login_required
def withdraw_view(request, pk):
    application = get_object_or_404(Application, pk=pk, student=request.user)
    if application.status == 'applied':
        application.delete()
        messages.success(request, 'Application withdrawn successfully!')
    else:
        messages.error(request, 'You cannot withdraw this application!')
    return redirect('my_applications')


@login_required
def post_drive_view(request):
    if request.user.role not in ['recruiter', 'admin']:
        messages.error(request, 'Only recruiters can post jobs!')
        return redirect('drive_list')

    if request.method == 'POST':
        PlacementDrive.objects.create(
            posted_by       = request.user,
            company         = request.POST['company'],
            role            = request.POST['role'],
            description     = request.POST['description'],
            location        = request.POST['location'],
            package         = request.POST['package'],
            job_type        = request.POST['job_type'],
            eligible_branch = request.POST['eligible_branch'],
            min_cgpa        = request.POST['min_cgpa'],
            skills_required = request.POST['skills_required'],
            deadline        = request.POST['deadline'],
        )
        messages.success(request, 'Placement drive posted successfully!')
        return redirect('drive_list')

    return render(request, 'placements/post_drive.html')


@login_required
def my_interviews_view(request):
    interviews = Interview.objects.filter(
        application__student=request.user
    ).order_by('scheduled_at')
    return render(request, 'placements/my_interviews.html', {
        'interviews': interviews
    })


@login_required
def schedule_interview_view(request, app_id):
    if request.user.role not in ['admin', 'recruiter']:
        messages.error(request, 'Access denied!')
        return redirect('dashboard')

    application = get_object_or_404(Application, pk=app_id)

    if request.method == 'POST':
        scheduled_at = request.POST['scheduled_at']
        location     = request.POST['location']
        meeting_link = request.POST['meeting_link']
        notes        = request.POST['notes']

        interview, created = Interview.objects.update_or_create(
            application=application,
            defaults={
                'scheduled_at': scheduled_at,
                'location':     location,
                'meeting_link': meeting_link,
                'notes':        notes,
                'status':       'scheduled'
            }
        )

        # Send portal notification
        send_notification(
            user=application.student,
            title=f'Interview Scheduled - {application.drive.company}',
            message=f'Your interview for {application.drive.role} at {application.drive.company} is scheduled on {scheduled_at}.',
            notif_type='general'
        )

        # Send email to student
        send_interview_email(
            student=application.student,
            drive=application.drive,
            scheduled_at=scheduled_at,
            location=location,
            meeting_link=meeting_link,
            notes=notes
        )

        messages.success(request, 'Interview scheduled successfully!')
        return redirect('admin_dashboard')

    return render(request, 'placements/schedule_interview.html', {
        'application': application
    })



@login_required
def recruiter_applicants_view(request):
    if request.user.role not in ['recruiter', 'admin']:
        return redirect('drive_list')
    drives = PlacementDrive.objects.filter(posted_by=request.user)
    selected_drive_id = request.GET.get('drive')
    applications = []
    selected_drive = None
    if selected_drive_id:
        selected_drive = get_object_or_404(PlacementDrive, pk=selected_drive_id, posted_by=request.user)
        applications = Application.objects.filter(drive=selected_drive).select_related('student', 'student__studentprofile')
    return render(request, 'placements/recruiter_applicants.html', {
        'drives': drives,
        'applications': applications,
        'selected_drive': selected_drive,
    })
