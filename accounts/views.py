from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import User
from placements.models import PlacementDrive, Application
from students.models import StudentProfile
from notifications.views import send_notification


def landing_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'landing.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']
        first_name = request.POST['first_name']
        last_name = request.POST['last_name']
        phone = request.POST['phone']
        role = request.POST['role']

        if password1 != password2:
            messages.error(request, 'Passwords do not match!')
            return redirect('register')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken!')
            return redirect('register')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=role
        )

        messages.success(request, 'Account created! Please login.')
        return redirect('login')

    return render(request, 'accounts/register.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.first_name}!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password!')

    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully!')
    return redirect('landing')


def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'dashboard.html', {'user': request.user})


def admin_dashboard_view(request):
    if not request.user.is_authenticated or request.user.role != 'admin':
        messages.error(request, 'Access denied!')
        return redirect('dashboard')

    students = User.objects.filter(role='student')
    recruiters = User.objects.filter(role='recruiter')
    drives = PlacementDrive.objects.all().order_by('-created_at')
    apps = Application.objects.all().order_by('-applied_at')

    total_students = students.count()
    total_recruiters = recruiters.count()
    total_drives = drives.count()
    total_apps = apps.count()
    selected_students = apps.filter(status='selected').count()

    return render(request, 'accounts/admin_dashboard.html', {
        'students': students,
        'recruiters': recruiters,
        'drives': drives,
        'apps': apps,
        'total_students': total_students,
        'total_recruiters': total_recruiters,
        'total_drives': total_drives,
        'total_apps': total_apps,
        'selected_students': selected_students,
    })


def update_application_status(request, pk):
    if not request.user.is_authenticated or request.user.role != 'admin':
        messages.error(request, 'Access denied!')
        return redirect('dashboard')

    app = get_object_or_404(Application, pk=pk)
    status = request.POST.get('status')

    if status in ['applied', 'shortlisted', 'rejected', 'selected']:
        app.status = status
        app.save()

        send_notification(
            user=app.student,
            title=f'Application Update - {app.drive.company}',
            message=f'Your application for {app.drive.role} at {app.drive.company} has been {status}!',
            notif_type=status if status in ['shortlisted', 'rejected', 'selected'] else 'general'
        )

        from campus_connect.email_utils import send_status_update_email
        send_status_update_email(app.student, app.drive, status)

        messages.success(request, f'Application status updated to {status}!')

    return redirect('admin_dashboard')


@login_required
def stats_view(request):
    from placements.models import PlacementDrive, Application
    from django.db.models import Count
    from django.db.models.functions import TruncMonth

    total_students = User.objects.filter(role='student').count()
    total_drives = PlacementDrive.objects.count()
    total_applications = Application.objects.count()
    selected_students = Application.objects.filter(status='selected').count()

    branch_data = (
        Application.objects
        .filter(status='selected')
        .values('student__studentprofile__branch')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    company_data = (
        Application.objects
        .filter(status='selected')
        .values('drive__company')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    status_data = (
        Application.objects
        .values('status')
        .annotate(count=Count('id'))
    )
    monthly_data = (
        Application.objects
        .annotate(month=TruncMonth('applied_at'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )

    return render(request, 'accounts/stats.html', {
        'total_students': total_students,
        'total_drives': total_drives,
        'total_applications': total_applications,
        'selected_students': selected_students,
        'placement_rate': round((selected_students / total_students * 100), 1) if total_students else 0,
        'branch_labels': [b['student__studentprofile__branch'] or 'Unknown' for b in branch_data],
        'branch_counts': [b['count'] for b in branch_data],
        'company_labels': [c['drive__company'] for c in company_data],
        'company_counts': [c['count'] for c in company_data],
        'status_labels': [s['status'] for s in status_data],
        'status_counts': [s['count'] for s in status_data],
        'monthly_labels': [m['month'].strftime('%b %Y') for m in monthly_data if m['month']],
        'monthly_counts': [m['count'] for m in monthly_data if m['month']],
    })


@login_required
def export_students_csv(request):
    if request.user.role != 'admin':
        return redirect('dashboard')
    import csv
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="students.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Email', 'Username', 'Branch', 'CGPA', 'Roll Number', 'Passing Year', 'Skills', 'LinkedIn', 'GitHub'])
    for user in User.objects.filter(role='student'):
        try:
            p = user.studentprofile
            writer.writerow([user.get_full_name(), user.email, user.username, p.branch, p.cgpa, p.roll_number, p.passing_year, p.skills, p.linkedin, p.github])
        except:
            writer.writerow([user.get_full_name(), user.email, user.username, '', '', '', '', '', '', ''])
    return response

@login_required
def search_students_view(request):
    if request.user.role not in ['recruiter', 'admin']:
        return redirect('dashboard')
    from students.models import StudentProfile
    students = StudentProfile.objects.select_related('user').all()
    branch = request.GET.get('branch', '')
    skill = request.GET.get('skill', '')
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
    return render(request, 'accounts/search_students.html', {
        'students': students,
        'branch': branch,
        'skill': skill,
        'min_cgpa': min_cgpa,
    })
