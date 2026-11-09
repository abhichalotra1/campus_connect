from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from accounts.decorators import is_verified_recruiter
from campus_connect.forms_util import discard_unsaved_files, flash_form_errors
from .forms import RecruiterProfileForm, StudentProfileForm, UserNameForm
from .models import StudentProfile, RecruiterProfile
from placements.models import PlacementDrive


@login_required
def profile_view(request):
    user = request.user

    if user.role == 'student':
        profile, _ = StudentProfile.objects.get_or_create(user=user)
        return render(request, 'students/profile.html', {
            'profile': profile,
            'missing_fields': profile.missing_required_fields(),
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
        profile, _ = StudentProfile.objects.get_or_create(user=user)

        if request.method == 'POST':
            form = StudentProfileForm(request.POST, request.FILES, instance=profile)
            name_form = UserNameForm(request.POST, instance=user)
            profile_ok, name_ok = form.is_valid(), name_form.is_valid()
            if profile_ok and name_ok:
                with transaction.atomic():
                    name_form.save()
                    form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
            flash_form_errors(request, form, name_form)
            discard_unsaved_files(profile)
            # fall through: the page shows the valid edits so far; nothing was saved

        return render(request, 'students/edit_profile.html', {
            'profile': profile,
            'branch_choices': StudentProfile.BRANCH_CHOICES,
            'missing_fields': profile.missing_required_fields(),
        })

    elif user.role == 'recruiter':
        profile, _ = RecruiterProfile.objects.get_or_create(user=user)

        if request.method == 'POST':
            form = RecruiterProfileForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, 'Recruiter profile updated successfully!')
                return redirect('profile')
            flash_form_errors(request, form)
            discard_unsaved_files(profile)

        return render(request, 'students/edit_recruiter_profile.html', {'profile': profile})

    elif user.role == 'admin':
        if request.method == 'POST':
            form = UserNameForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
            flash_form_errors(request, form)
            # fall through: the page shows the valid edits so far; nothing was saved

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

