import json
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from accounts.decorators import verified_recruiter_required
from accounts.models import User 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required

# ── MODELS IMPORT ──
from .models import PlacementDrive, Application, Interview, Bookmark, Conversation, ChatMessage
from students.models import StudentProfile
from notifications.views import send_notification
from campus_connect.email_utils import (
    send_application_email,
    send_recruiter_email,
    send_interview_email,
    send_withdrawal_email,
    send_status_update_email,
)


# ══════════════════════════════════════════════════════════════
# CHAT VIEWS
# ══════════════════════════════════════════════════════════════

# ── 1. MAIN CHAT ROOM VIEW ──────────────────────────────────────────────
@login_required
def chat_room_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    
    # Determine if the user is just observing (Admin viewing someone else's chat)
    is_observer = False
    if request.user.role == 'admin' and request.user != conversation.student and request.user != conversation.recruiter:
        is_observer = True
    
    # Security: Only the student, recruiter, or admin can access this chat
    if request.user != conversation.student and request.user != conversation.recruiter and request.user.role != 'admin':
        messages.error(request, 'Access denied to this chat.')
        return redirect('dashboard')

    # Update heartbeat (for online status)
    User.objects.filter(pk=request.user.pk).update(last_active_at=timezone.now())

    # Check if student's chat is currently unlocked
    is_student_unlocked = False
    if request.user.role == 'student' and conversation.student_chat_unlocked_until:
        if timezone.now() < conversation.student_chat_unlocked_until:
            is_student_unlocked = True
        else:
            conversation.student_chat_unlocked_until = None
            conversation.save()

    # Check if the other user is online (active in the last 2 minutes)
    other_user = conversation.recruiter if request.user == conversation.student else conversation.student
    is_other_online = False
    if other_user.last_active_at:
        is_other_online = (timezone.now() - other_user.last_active_at).total_seconds() < 120

    context = {
        'conversation': conversation,
        'is_student_unlocked': is_student_unlocked,
        'is_other_online': is_other_online,
        'other_user_name': other_user.get_full_name() or other_user.username,
        'is_observer': is_observer,
    }
    return render(request, 'placements/chat_room.html', context)


# ── 2. AJAX POLLING: FETCH MESSAGES ─────────────────────────────────────
@login_required
def fetch_messages_api(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    
    if request.user != conversation.student and request.user != conversation.recruiter and request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # Update heartbeat safely
    User.objects.filter(pk=request.user.pk).update(last_active_at=timezone.now())

    # Get messages newer than the last_message_id sent by the frontend
    last_message_id = request.GET.get('last_message_id', 0)
    messages = ChatMessage.objects.filter(
        conversation=conversation, 
        id__gt=last_message_id
    ).order_by('created_at')

    messages_data = []
    for msg in messages:
        msg_data = {
            'id': msg.id,
            'sender': msg.sender,
            'message_type': msg.message_type,
            'content': msg.content,
            'template_action': msg.template_action,
            'file_url': msg.file.url if msg.file else None,
            'file_category': msg.file_category,
            'time': msg.created_at.strftime('%I:%M %p'),
        }
        messages_data.append(msg_data)

    # Check if student is currently unlocked (to update UI timer dynamically)
    is_student_unlocked = False
    unlock_time_remaining = 0
    if conversation.student_chat_unlocked_until:
        if timezone.now() < conversation.student_chat_unlocked_until:
            is_student_unlocked = True
            unlock_time_remaining = (conversation.student_chat_unlocked_until - timezone.now()).total_seconds()
        else:
            conversation.student_chat_unlocked_until = None
            conversation.save()

    # Check other user online status
    other_user = conversation.recruiter if request.user == conversation.student else conversation.student
    is_other_online = False
    if other_user.last_active_at:
        is_other_online = (timezone.now() - other_user.last_active_at).total_seconds() < 120

    return JsonResponse({
        'messages': messages_data,
        'is_student_unlocked': is_student_unlocked,
        'unlock_time_remaining': int(unlock_time_remaining),
        'is_other_online': is_other_online,
    })


# ── 3. SEND MESSAGE API ─────────────────────────────────────────────────
@require_POST
@login_required
def send_message_api(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    
    # Security check
    if request.user != conversation.student and request.user != conversation.recruiter and request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    # Observer check (Admin viewing someone else's chat cannot send messages)
    is_observer = request.user.role == 'admin' and request.user != conversation.student and request.user != conversation.recruiter
    if is_observer:
        return JsonResponse({'error': 'Observers cannot send messages.'}, status=403)

    sender_role = 'recruiter' if request.user == conversation.recruiter else 'student'

    # ── RULE ENFORCEMENT: Can the student send this? ──
    if sender_role == 'student':
        message_type = request.POST.get('message_type')
        
        # If they want to send free text, we must check the timer!
        if message_type == 'text':
            is_currently_unlocked = False
            if conversation.student_chat_unlocked_until:
                if timezone.now() < conversation.student_chat_unlocked_until:
                    is_currently_unlocked = True
            
            if not is_currently_unlocked:
                return JsonResponse({'error': 'Chat is locked. You can only use predefined queries.'}, status=403)

    # ── CREATE THE MESSAGE ──
    msg = ChatMessage.objects.create(
        conversation=conversation,
        sender=sender_role,
        message_type=request.POST.get('message_type', 'text'),
        content=request.POST.get('content', ''),
        template_action=request.POST.get('template_action', ''),
        file_category=request.POST.get('file_category', ''),
    )

    # Handle file upload if exists
    if 'file' in request.FILES:
        msg.file = request.FILES['file']
        msg.save()

    return JsonResponse({'status': 'success', 'message_id': msg.id})


# ── 4. UNLOCK STUDENT CHAT ─────────────────────────────────────────────
@require_POST
@login_required
def unlock_student_chat(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    
    # Only the recruiter or admin (who posted the drive) can unlock the chat
    if request.user != conversation.recruiter and request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # Unlock for 5 minutes
    conversation.student_chat_unlocked_until = timezone.now() + timezone.timedelta(minutes=5)
    conversation.save()

    # Drop a system message so the student knows
    ChatMessage.objects.create(
        conversation=conversation,
        sender='system',
        message_type='system',
        content=f"{request.user.get_full_name()} has unlocked the chat for 5 minutes. You can type freely now."
    )

    return JsonResponse({'status': 'success', 'unlocked_until': conversation.student_chat_unlocked_until.isoformat()})


# ── 5. GET OR CREATE CHAT VIEW ──────────────────────────────────────────
@login_required
def get_or_create_chat_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id)
    
    # Security: Only the student, recruiter, or admin can start this chat
    if request.user != application.student and request.user != application.drive.posted_by and request.user.role != 'admin':
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
        
    # Get the conversation (it should already exist if shortlisted, but get_or_create is safe)
    conv, created = Conversation.objects.get_or_create(
        application=application,
        defaults={
            'student': application.student,
            'recruiter': application.drive.posted_by,
            'drive': application.drive
        }
    )
    
    # Redirect to the actual chat room
    return redirect('chat_room', conversation_id=conv.pk)


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
def apply_view(request, pk):
    drive = get_object_or_404(PlacementDrive, pk=pk)

    if request.method != 'POST':
        messages.error(request, "Invalid application method!")
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
        try:
            min_cgpa      = float(request.POST.get('min_cgpa', 0.0))
            salary_amount = float(request.POST.get('salary_amount', 0.0))
        except (ValueError, TypeError):
            messages.error(request, 'Please enter valid numbers for CGPA and Salary.')
            return render(request, 'placements/post_drive.html')

        if 'company_logo' not in request.FILES:
            messages.error(request, 'Company Logo is compulsory!')
            return render(request, 'placements/post_drive.html')

        PlacementDrive.objects.create(
            posted_by       = request.user,
            company         = request.POST.get('company'),
            company_logo    = request.FILES['company_logo'],
            role            = request.POST.get('role'),
            description     = request.POST.get('description'),
            location        = request.POST.get('location'),
            salary_amount   = salary_amount,
            salary_type     = request.POST.get('salary_type'),
            job_type        = request.POST.get('job_type'),
            eligible_branch = request.POST.get('eligible_branch'),
            min_cgpa        = min_cgpa,
            skills_required = request.POST.get('skills_required', ''),
            deadline        = request.POST.get('deadline'),
        )
        messages.success(request, 'Placement drive posted successfully!')
        return redirect('recruiter_dashboard')

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

    application = get_object_or_404(Application, pk=app_id)

    if request.method == 'POST':
        scheduled_at = request.POST['scheduled_at']
        location     = request.POST.get('location', '')
        meeting_link = request.POST.get('meeting_link', '')
        notes        = request.POST.get('notes', '')

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

        send_notification(
            user=application.student,
            title=f'Interview Scheduled - {application.drive.company}',
            message=f'Your interview for {application.drive.role} at {application.drive.company} is scheduled on {scheduled_at}.',
            notif_type='general'
        )

        send_interview_email(
            student=application.student,
            drive=application.drive,
            scheduled_at=scheduled_at,
            location=location,
            meeting_link=meeting_link,
            notes=notes,
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

    my_drives         = PlacementDrive.objects.filter(posted_by=request.user)
    selected_drive_id = request.GET.get('drive')
    applications      = []
    selected_drive    = None

    if selected_drive_id:
        selected_drive = get_object_or_404(PlacementDrive, pk=selected_drive_id, posted_by=request.user)
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


def company_profile_view(request, user_id):
    recruiter = get_object_or_404(User, pk=user_id, role='recruiter')

    from students.models import RecruiterProfile
    profile, created = RecruiterProfile.objects.get_or_create(user=recruiter)

    drives = PlacementDrive.objects.filter(posted_by=recruiter, status='active').order_by('-created_at')

    return render(request, 'placements/company_profile.html', {
        'recruiter': recruiter,
        'profile':   profile,
        'drives':    drives,
    })

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
        
    return redirect(request.META.get('HTTP_REFERER', 'saved_jobs'))