from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import StudentProfile, RecruiterProfile
from placements.models import PlacementDrive, Application


@login_required
def profile_view(request):
    user = request.user

    if user.role == 'student':
        profile, _ = StudentProfile.objects.get_or_create(
            user=user,
            defaults={'branch': 'CSE', 'roll_number': 'N/A', 'passing_year': 2025}
        )
        return render(request, 'students/profile.html', {
            'profile': profile,
        })

    elif user.role == 'recruiter':
        profile, _ = RecruiterProfile.objects.get_or_create(user=user)
        
        # Fetch the drives posted by this recruiter to show on their profile
        from placements.models import PlacementDrive
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
            defaults={'branch': 'CSE', 'roll_number': 'N/A', 'passing_year': 2025}
        )

        if request.method == 'POST':
            profile.branch         = request.POST.get('branch', profile.branch)
            profile.roll_number    = request.POST.get('roll_number', profile.roll_number)
            profile.passing_year   = request.POST.get('passing_year', profile.passing_year)
            profile.skills         = request.POST.get('skills', profile.skills)
            profile.certifications = request.POST.get('certifications', profile.certifications)
            profile.about          = request.POST.get('about', profile.about)
            profile.linkedin       = request.POST.get('linkedin', profile.linkedin)
            profile.github         = request.POST.get('github', profile.github)

            try:
                profile.cgpa = float(request.POST.get('cgpa', profile.cgpa))
            except (ValueError, TypeError):
                pass

            if 'resume' in request.FILES:
                profile.resume = request.FILES['resume']
            if 'profile_pic' in request.FILES:
                profile.profile_pic = request.FILES['profile_pic']

            profile.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')

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

            profile.save()
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