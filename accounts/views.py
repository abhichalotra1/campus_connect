from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from campus_connect.forms_util import flash_form_errors
from campus_connect.pagination import paginate
from .audit import log_action
from .notify import notify_admins
from .decorators import admin_required, is_verified_recruiter
from .forms import VerificationRequestForm
from .models import User
from placements.models import PlacementDrive, Application, Interview
from students.models import StudentProfile, RecruiterProfile
from notifications.models import Notification
from notifications.views import send_notification
from campus_connect.email_utils import send_status_update_email


def landing_view(request):
    return render(request, 'landing.html')


def _validate_registration(data):
    """Return a list of error strings for the registration form data."""
    errors = []

    username = data['username']
    if not username:
        errors.append('Username is required.')
    else:
        try:
            User._meta.get_field('username').run_validators(username)
            if len(username) > User._meta.get_field('username').max_length:
                raise ValidationError('too long')
        except ValidationError:
            errors.append('Username may only contain letters, numbers and @/./+/-/_ (max 150 characters).')
        else:
            if User.objects.filter(username__iexact=username).exists():
                errors.append('Username already taken!')

    email = data['email']
    if not email:
        errors.append('Email is required.')
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors.append('Enter a valid email address.')
        else:
            if User.objects.filter(email__iexact=email).exists():
                errors.append('An account with this email already exists.')

    for field, label in (('first_name', 'First name'), ('last_name', 'Last name')):
        if len(data[field]) > User._meta.get_field(field).max_length:
            errors.append(f'{label} is too long.')
    if len(data['phone']) > User._meta.get_field('phone').max_length:
        errors.append('Phone number is too long.')

    if data['password1'] != data['password2']:
        errors.append('Passwords do not match!')
    else:
        # Runs the validators from AUTH_PASSWORD_VALIDATORS (length, common, numeric, similarity).
        candidate = User(username=username, email=email,
                         first_name=data['first_name'], last_name=data['last_name'])
        try:
            validate_password(data['password1'], user=candidate)
        except ValidationError as exc:
            errors.extend(exc.messages)
    return errors


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = {}
    if request.method == 'POST':
        form = {
            'username':   request.POST.get('username', '').strip(),
            'email':      request.POST.get('email', '').strip(),
            'password1':  request.POST.get('password1', ''),
            'password2':  request.POST.get('password2', ''),
            'first_name': request.POST.get('first_name', '').strip(),
            'last_name':  request.POST.get('last_name', '').strip(),
            'phone':      request.POST.get('phone', '').strip(),
            'role':       request.POST.get('role', 'student'),
        }
        if form['role'] not in ['student', 'recruiter']:
            form['role'] = 'student'

        errors = _validate_registration(form)
        if errors:
            for err in errors:
                messages.error(request, err)
            # Re-show the form with what they typed (never send passwords back).
            form['password1'] = form['password2'] = ''
            return render(request, 'accounts/register.html', {'form': form})

        try:
            with transaction.atomic():
                User.objects.create_user(
                    username=form['username'],
                    email=form['email'],
                    password=form['password1'],
                    first_name=form['first_name'],
                    last_name=form['last_name'],
                    phone=form['phone'],
                    role=form['role'],
                )
        except IntegrityError:
            # Two sign-ups with the same username at the same moment: the other one won.
            messages.error(request, 'That username was just taken. Please choose another.')
            form['password1'] = form['password2'] = ''
            return render(request, 'accounts/register.html', {'form': form})

        messages.success(request, 'Account created! Please login.')
        return redirect('login')

    return render(request, 'accounts/register.html', {'form': form})


def _safe_next(request):
    """Return the ?next= target only if it points back at this site."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return ''


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if not username or not password:
            messages.error(request, 'Please enter both your username/email and password.')
            return render(request, 'accounts/login.html')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, 'Your account has been deactivated by the administrator.')
                return redirect('login')
            login(request, user)
            messages.success(request, f'Welcome back, {user.first_name or user.username}!')
            return redirect(_safe_next(request) or 'dashboard')
        else:
            messages.error(request, 'Invalid username or password!')

    return render(request, 'accounts/login.html', {'next': _safe_next(request)})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully!')
    return redirect('landing')


@login_required
def dashboard_view(request):
    user = request.user
    context = {'user': user}

    open_drives = PlacementDrive.objects.open()
    context['open_drives_count'] = open_drives.count()
    context['recent_drives'] = open_drives.order_by('-created_at')[:5]

    context['notifications'] = Notification.objects.filter(user=user).order_by('-created_at')[:4]
    context['unread_count'] = Notification.objects.filter(user=user, is_read=False).count()

    if user.role == 'student':
        apps = Application.objects.filter(student=user)
        context['applications_count'] = apps.count()
        context['shortlisted_count'] = apps.filter(status='shortlisted').count()
        context['my_applications'] = apps.order_by('-applied_at')[:4]
        context['selected_applications'] = apps.filter(status='selected')

        interviews = Interview.objects.filter(
            application__student=user,
            scheduled_at__gte=timezone.now()
        ).order_by('scheduled_at')
        context['interviews_count'] = interviews.count()
        context['upcoming_interviews'] = interviews[:2]

        profile = StudentProfile.objects.filter(user=user).first() or StudentProfile(user=user)
        context['profile_completion'] = profile.profile_completion()
        context['missing_fields'] = profile.missing_required_fields()

    elif user.role == 'recruiter':
        my_drives = PlacementDrive.objects.filter(posted_by=user)
        apps = Application.objects.filter(drive__in=my_drives)
        context['applications_count'] = apps.count()
        context['shortlisted_count'] = apps.filter(status='shortlisted').count()
        context['interviews_count'] = Interview.objects.filter(
            application__in=apps, scheduled_at__gte=timezone.now()
        ).count()
        context['my_drives'] = my_drives.order_by('-created_at')[:5]

    elif user.role == 'admin':
        apps = Application.objects.all()
        context['applications_count'] = apps.count()
        context['shortlisted_count'] = apps.filter(status='shortlisted').count()
        context['interviews_count'] = Interview.objects.filter(
            scheduled_at__gte=timezone.now()
        ).count()
        context['total_students'] = User.objects.filter(role='student').count()
        context['total_recruiters'] = User.objects.filter(role='recruiter').count()

    return render(request, 'dashboard.html', context)


ADMIN_TABS = ('pending', 'applications', 'drives', 'students', 'recruiters')
ADMIN_PAGE_SIZE = 15
_ADMIN_DASH_PATH = '/accounts/admin-dashboard/'


def _admin_back(request):
    """Send the admin back to the exact tab, filter and page they acted from."""
    target = request.POST.get('next', '')
    if (target.startswith(_ADMIN_DASH_PATH)
            and url_has_allowed_host_and_scheme(
                target, allowed_hosts={request.get_host()}, require_https=request.is_secure())):
        return redirect(target)
    return redirect('admin_dashboard')


def _search(queryset, text, *fields):
    """Every word typed must appear in at least one of the fields (so "john smith" works)."""
    for word in text.split()[:5]:
        condition = Q()
        for field in fields:
            condition |= Q(**{f'{field}__icontains': word})
        queryset = queryset.filter(condition)
    return queryset


@admin_required
def admin_dashboard_view(request):
    today = timezone.localdate()

    # The overview numbers are a handful of cheap COUNT queries; the big lists below are
    # loaded one tab and one page at a time, so the page stays fast however much data grows.
    people = User.objects.aggregate(
        students=Count('pk', filter=Q(role='student')),
        recruiters=Count('pk', filter=Q(role='recruiter')),
    )
    pending_users = User.objects.filter(role='recruiter', recruiterprofile__verification_status='pending')
    counts = {
        'students': people['students'],
        'recruiters': people['recruiters'],
        'drives': PlacementDrive.objects.count(),
        'applications': Application.objects.count(),
        'pending': pending_users.count(),
    }
    # Distinct students: one student selected in two drives is still one placed student.
    placed_students = Application.objects.filter(status='selected').values('student').distinct().count()
    placement_rate = round(placed_students * 100 / counts['students']) if counts['students'] else 0

    tab = request.GET.get('tab', '')
    if tab not in ADMIN_TABS:
        tab = 'pending' if counts['pending'] else 'applications'
    q = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', '')
    state = request.GET.get('state', '')

    if tab == 'pending':
        queryset = pending_users.select_related('recruiterprofile').order_by(
            'recruiterprofile__verification_requested_at', 'pk')
        queryset = _search(queryset, q, 'username', 'email', 'first_name', 'last_name',
                           'recruiterprofile__company_name')
        status = state = ''

    elif tab == 'applications':
        if status not in [key for key, _ in Application.STATUS_CHOICES]:
            status = ''
        queryset = Application.objects.select_related('student', 'drive').order_by('-applied_at', '-pk')
        if status:
            queryset = queryset.filter(status=status)
        queryset = _search(queryset, q, 'student__username', 'student__first_name', 'student__last_name',
                           'student__email', 'drive__company', 'drive__role')
        state = ''

    elif tab == 'drives':
        drives = PlacementDrive.objects.all()
        if state == 'open':
            drives = drives.open()
        elif state == 'closed':
            drives = drives.filter(status='closed')
        elif state == 'expired':
            drives = drives.filter(status='active', deadline__lt=today)
        else:
            state = ''
        queryset = drives.select_related('posted_by').annotate(app_count=Count('application')).order_by(
            '-created_at', '-pk')
        queryset = _search(queryset, q, 'company', 'role', 'location')
        status = ''

    elif tab == 'students':
        queryset = User.objects.filter(role='student').select_related('studentprofile').order_by(
            '-date_joined', '-pk')
        if state in ('active', 'inactive'):
            queryset = queryset.filter(is_active=(state == 'active'))
        else:
            state = ''
        queryset = _search(queryset, q, 'username', 'first_name', 'last_name', 'email',
                           'studentprofile__roll_number')
        status = ''

    else:  # recruiters
        queryset = User.objects.filter(role='recruiter').select_related('recruiterprofile').order_by(
            '-date_joined', '-pk')
        if state == 'inactive':
            queryset = queryset.filter(is_active=False)
        elif state == 'not_requested':
            queryset = queryset.filter(
                Q(recruiterprofile__isnull=True) | Q(recruiterprofile__verification_status='not_requested'))
        elif state in ('approved', 'pending', 'rejected'):
            queryset = queryset.filter(recruiterprofile__verification_status=state)
        else:
            state = ''
        queryset = _search(queryset, q, 'username', 'first_name', 'last_name', 'email',
                           'recruiterprofile__company_name')
        status = ''

    rows, page_query = paginate(request, queryset, per_page=ADMIN_PAGE_SIZE)

    return render(request, 'accounts/admin_dashboard.html', {
        'tab': tab, 'q': q, 'status': status, 'state': state,
        'rows': rows, 'page_obj': rows, 'page_query': page_query,
        'counts': counts,
        'open_drives': PlacementDrive.objects.open().count(),
        'placed_students': placed_students,
        'placement_rate': placement_rate,
        'status_choices': Application.STATUS_CHOICES,
        'next_url': request.get_full_path(),
    })


@login_required
@require_POST
def update_application_status(request, pk):
    app = get_object_or_404(Application, pk=pk)

    if request.user.role != 'admin' and app.drive.posted_by != request.user:
        messages.error(request, 'Access denied!')
        return redirect('dashboard')

    if request.method == 'POST':
        status = request.POST.get('status')

        if status in ['applied', 'shortlisted', 'rejected', 'selected']:
            if status == app.status:
                # Nothing changed: don't notify or email the student a second time
                messages.info(request, f'Application is already marked {status}.')
            else:
                old_status = app.status
                app.status = status
                app.save()
                log_action(request, 'application_status_changed',
                           f'{app.student.username} -> {app.drive.company} / {app.drive.role}',
                           f'{old_status} -> {status}')

                if status == 'applied':
                    note = (f'Your application for {app.drive.role} at {app.drive.company} '
                            'has been moved back to under review.')
                else:
                    note = f'Your application for {app.drive.role} at {app.drive.company} has been {status}!'
                send_notification(
                    user=app.student,
                    title=f'Application Update - {app.drive.company}',
                    message=note,
                    notif_type=status if status in ['shortlisted', 'rejected', 'selected'] else 'general'
                )

                send_status_update_email(app.student, app.drive, status)
                messages.success(request, f'Application status updated to {status}!')

    if request.user.role == 'recruiter':
        return redirect('recruiter_applicants')
    else:
        return _admin_back(request)


def _csv_safe(value):
    """Neutralise spreadsheet formulas in user-supplied text (CSV injection)."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@admin_required
def export_students_csv(request):
    import csv
    from django.http import HttpResponse

    log_action(request, 'export_students_csv', details='Full student CSV export')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="students.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Email', 'Username', 'Branch', 'CGPA',
                     'Roll Number', 'Passing Year', 'Skills', 'LinkedIn', 'GitHub'])

    for user in User.objects.filter(role='student').select_related('studentprofile'):
        try:
            p = user.studentprofile
            writer.writerow([_csv_safe(c) for c in [
                user.get_full_name(), user.email, user.username,
                p.branch, p.cgpa, p.roll_number, p.passing_year,
                p.skills, p.linkedin, p.github
            ]])
        except StudentProfile.DoesNotExist:
            writer.writerow([_csv_safe(c) for c in [user.get_full_name(), user.email, user.username,
                             '', '', '', '', '', '', '']])
    return response


@login_required
def search_students_view(request):
    if request.user.role not in ['recruiter', 'admin']:
        return redirect('dashboard')
    # Browsing every student's contact details and resume needs an approved recruiter account
    if request.user.role == 'recruiter' and not is_verified_recruiter(request.user):
        return redirect('verification_status')

    students = StudentProfile.objects.select_related('user').order_by('user__first_name', 'user__last_name', 'pk')
    branch   = request.GET.get('branch', '')
    skill    = request.GET.get('skill', '')
    min_cgpa = request.GET.get('min_cgpa', '')

    if branch:
        students = students.filter(branch=branch)
    if skill:
        students = students.filter(skills__icontains=skill)
    if min_cgpa:
        try:
            students = students.filter(cgpa__gte=float(min_cgpa))
        except ValueError:
            pass

    students, page_query = paginate(request, students, per_page=12)

    return render(request, 'accounts/search_students.html', {
        'students': students,
        'page_obj': students,
        'page_query': page_query,
        'branch':   branch,
        'skill':    skill,
        'min_cgpa': min_cgpa,
    })


# ── VERIFICATION VIEWS ────────────────────────────────────────────────────

@login_required
def verification_status_view(request):
    if request.user.role != 'recruiter':
        return redirect('dashboard')
    profile, _ = RecruiterProfile.objects.get_or_create(user=request.user)
    return render(request, 'accounts/verification_status.html', {'profile': profile})


@login_required
def request_verification_view(request):
    if request.user.role != 'recruiter':
        return redirect('dashboard')

    profile, _ = RecruiterProfile.objects.get_or_create(user=request.user)

    if profile.is_verified:
        return redirect('dashboard')

    if request.method == 'POST':
        form = VerificationRequestForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.verification_status       = 'pending'
            profile.verification_requested_at = timezone.now()
            profile.save()
            notify_admins(
                'New verification request',
                f'{profile.company_name or request.user.username} ({request.user.username}) '
                'asked to be verified as a recruiter.',
                'general')

            messages.success(request, 'Verification request submitted! We will review it shortly.')
            return redirect('verification_status')
        flash_form_errors(request, form)
        # fall through: the page shows the valid edits so far; nothing was saved

    return render(request, 'accounts/request_verification.html', {'profile': profile})


@admin_required
@require_POST
def admin_verify_recruiter(request, user_id):
    recruiter_user = get_object_or_404(User, pk=user_id, role='recruiter')
    profile, _     = RecruiterProfile.objects.get_or_create(user=recruiter_user)

    if request.method == 'POST':
        action       = request.POST.get('action')
        admin_remark = request.POST.get('admin_remark', '').strip()[:500]
        if action == 'reject' and not admin_remark:
            messages.error(request, 'Please give a reason for rejecting, so the recruiter knows what to fix.')
            return _admin_back(request)
        profile.admin_remark = admin_remark

        if action == 'approve':
            profile.verification_status = 'approved'
            profile.verified_at         = timezone.now()
            profile.save()

            send_notification(
                user=recruiter_user,
                title='Verification Approved!',
                message='Your recruiter account has been verified. You can now post placement drives.',
                notif_type='general'
            )
            log_action(request, 'recruiter_approved', recruiter_user.username, admin_remark)
            messages.success(request, f'{recruiter_user.username} has been verified.')

        elif action == 'reject':
            profile.verification_status = 'rejected'
            profile.save()

            send_notification(
                user=recruiter_user,
                title='Verification Update',
                message=f'Your verification request was not approved. Reason: {admin_remark}',
                notif_type='general'
            )
            log_action(request, 'recruiter_rejected', recruiter_user.username, admin_remark)
            messages.warning(request, f'{recruiter_user.username} verification rejected.')

    return _admin_back(request)


# ── ADMIN DRIVE MODERATION ────────────────────────────────────────────────

@admin_required
@require_POST
def admin_toggle_drive_status(request, drive_id):
    drive = get_object_or_404(PlacementDrive, pk=drive_id)

    if request.method == 'POST':
        label = f'{drive.company} - {drive.role}'
        if drive.status == 'active':
            drive.status = 'closed'
            messages.warning(request, f'Drive "{label}" has been forcefully closed.')
            action = 'drive_closed'
        else:
            drive.status = 'active'
            action = 'drive_reopened'
            if drive.deadline < timezone.localdate():
                messages.warning(
                    request, f'Drive "{label}" was reopened, but its deadline ({drive.deadline:%d %b %Y}) '
                             'has passed, so students still cannot apply. Edit the drive to set a new deadline.')
            else:
                messages.success(request, f'Drive "{label}" has been reopened.')

        drive.save()
        log_action(request, action, label, f'Drive #{drive.pk}')

    return _admin_back(request)


# ── ADMIN USER MANAGEMENT (SOFT DELETE) ───────────────────────────────────

@admin_required
@require_POST
def admin_toggle_user_status(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)

    # Prevent admin from deactivating themselves
    if target_user == request.user:
        messages.error(request, "You cannot deactivate your own account!")
        return _admin_back(request)

    if request.method == 'POST':
        deactivating = target_user.is_active

        # Admins can't lock each other out; this also guarantees one admin always remains
        if deactivating and target_user.role == 'admin':
            messages.error(request, 'Admin accounts cannot be deactivated here. '
                                    'Change the role in Django admin first if you really need to.')
            return _admin_back(request)

        target_user.is_active = not target_user.is_active
        target_user.save()

        closed = 0
        if deactivating and target_user.role == 'recruiter':
            # A deactivated recruiter can't manage their drives, so stop new applications
            closed = PlacementDrive.objects.filter(
                posted_by=target_user, status='active').update(status='closed')

        log_action(request, 'user_activated' if target_user.is_active else 'user_deactivated',
                   target_user.username,
                   f'{closed} active drive(s) closed' if closed else '')

        if target_user.is_active:
            messages.success(request, f'User {target_user.username} has been reactivated. '
                                      'Their closed drives stay closed; reopen them if needed.')
        else:
            extra = f' {closed} active drive(s) were closed.' if closed else ''
            messages.warning(request, f'User {target_user.username} has been deactivated. '
                                      f'They can no longer log in.{extra}')

    return _admin_back(request)