from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from accounts.decorators import is_verified_recruiter
from .models import StudentProfile, RecruiterProfile
from placements.models import PlacementDrive, Application


def _save_validated(request, profile):
    """Run model validators, then save. Returns True on success."""
    try:
        profile.full_clean()
    except ValidationError as e:
        for field, errors in e.message_dict.items():
            label = '' if field == '__all__' else field.replace('_', ' ').title() + ': '
            for err in errors:
                messages.error(request, f'{label}{err}')
        return False
    profile.save()
    return True


@login_required
def profile_view(request):
    user = request.user

    if user.role == 'student':
        profile, _ = StudentProfile.objects.get_or_create(
            user=user,
            defaults={'branch': 'CSE'}
        )
        return render(request, 'students/profile.html', {
            'profile': profile,
        })

    elif user.role == 'recruiter':
        profile, _ = RecruiterProfile.objects.get_or_create(user=user)

        # Fetch the drives posted by this recruiter to show on their profile
        my_drives = PlacementDrive.objects.filter(posted_by=user).order_by('-created_at')

        return render(request, 'students/recruiter_profile.html', {
            'profile': profile,
            'my_drives': my_drives,
        })

    elif user.role == 'admin':
        from accounts.models import User as UserModel
        permissions = [
            'Manage all students',
            'Manage all recruiters',
            'Post & close placement drives',
            'Update application statuses',
            'Export student data',
            'View platform statistics',
        ]
        return render(request, 'students/admin_profile.html', {
            'total_students':   UserModel.objects.filter(role='student').count(),
            'total_recruiters': UserModel.objects.filter(role='recruiter').count(),
            'permissions':      permissions,
        })

    return redirect('dashboard')


@login_required
def edit_profile_view(request):
    user = request.user

    if user.role == 'student':
        profile, _ = StudentProfile.objects.get_or_create(
            user=user,
            defaults={'branch': 'CSE'}
        )

        if request.method == 'POST':
            profile.branch         = request.POST.get('branch', profile.branch)
            profile.roll_number    = request.POST.get('roll_number', profile.roll_number) or None
            profile.skills         = request.POST.get('skills', profile.skills)
            profile.certifications = request.POST.get('certifications', profile.certifications)
            profile.about          = request.POST.get('about', profile.about)
            profile.linkedin       = request.POST.get('linkedin', profile.linkedin)
            profile.github         = request.POST.get('github', profile.github)

            # Blank number fields keep the old value; anything else is validated
            passing_year = request.POST.get('passing_year', '').strip()
            if passing_year:
                profile.passing_year = passing_year
            cgpa = request.POST.get('cgpa', '').strip()
            if cgpa:
                profile.cgpa = cgpa

            if 'resume' in request.FILES:
                profile.resume = request.FILES['resume']
            if 'profile_pic' in request.FILES:
                profile.profile_pic = request.FILES['profile_pic']

            if _save_validated(request, profile):
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
            # On error, fall through and re-render the form with the errors

        return render(request, 'students/edit_profile.html', {
            'profile': profile,
            'branch_choices': PlacementDrive.BRANCH_CHOICES,
        })

    elif user.role == 'recruiter':
        profile, _ = RecruiterProfile.objects.get_or_create(user=user)

        if request.method == 'POST':
            profile.company_name    = request.POST.get('company_name', profile.company_name)
            profile.industry        = request.POST.get('industry', profile.industry)
            profile.designation     = request.POST.get('designation', profile.designation)
            profile.company_website = request.POST.get('company_website', profile.company_website)
            profile.company_address = request.POST.get('company_address', profile.company_address)
            profile.about           = request.POST.get('about', profile.about)
            profile.linkedin        = request.POST.get('linkedin', profile.linkedin)

            if 'profile_pic' in request.FILES:
                profile.profile_pic = request.FILES['profile_pic']

            if _save_validated(request, profile):
                messages.success(request, 'Recruiter profile updated successfully!')
                return redirect('profile')

        return render(request, 'students/edit_recruiter_profile.html', {'profile': profile})

    elif user.role == 'admin':
        if request.method == 'POST':
            user.first_name = request.POST.get('first_name', user.first_name)
            user.last_name  = request.POST.get('last_name', user.last_name)
            user.phone      = request.POST.get('phone', user.phone)
            user.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')

        return render(request, 'students/edit_admin_profile.html')

    return redirect('dashboard')


@login_required
def resume_download_view(request, name):
    """Hand out a resume link only to people who may see it.

    Allowed: the student themself, admins, and approved recruiters. Everyone else gets 403.
    The browser is redirected to the file's real location (Cloudinary in production, the
    local /media/ file in development); the direct link is never put in a page.
    """
    profile = get_object_or_404(StudentProfile.objects.select_related('user'), resume=name)
    user = request.user
    if not (user == profile.user or user.role == 'admin' or is_verified_recruiter(user)):
        raise PermissionDenied

    cloud_url = getattr(profile.resume.storage, 'cloud_url', None)
    target = cloud_url(profile.resume.name) if cloud_url else profile.resume.url
    response = redirect(target)
    response['Cache-Control'] = 'private, no-store'
    return response

