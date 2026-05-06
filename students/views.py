from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import StudentProfile

@login_required
def profile_view(request):
    try:
        profile = StudentProfile.objects.get(user=request.user)
    except StudentProfile.DoesNotExist:
        profile = None

    return render(request, 'students/profile.html', {'profile': profile})


@login_required
def edit_profile_view(request):
    try:
        profile = StudentProfile.objects.get(user=request.user)
    except StudentProfile.DoesNotExist:
        profile = None

    if request.method == 'POST':
        branch          = request.POST['branch']
        cgpa            = request.POST['cgpa']
        roll_number     = request.POST['roll_number']
        passing_year    = request.POST['passing_year']
        skills          = request.POST['skills']
        certifications  = request.POST['certifications']
        about           = request.POST['about']
        linkedin        = request.POST['linkedin']
        github          = request.POST['github']

        if profile:
            profile.branch         = branch
            profile.cgpa           = cgpa
            profile.roll_number    = roll_number
            profile.passing_year   = passing_year
            profile.skills         = skills
            profile.certifications = certifications
            profile.about          = about
            profile.linkedin       = linkedin
            profile.github         = github

            if 'resume' in request.FILES:
                profile.resume = request.FILES['resume']
            if 'profile_pic' in request.FILES:
                profile.profile_pic = request.FILES['profile_pic']

            profile.save()
        else:
            profile = StudentProfile.objects.create(
                user=request.user,
                branch=branch, cgpa=cgpa,
                roll_number=roll_number, passing_year=passing_year,
                skills=skills, certifications=certifications,
                about=about, linkedin=linkedin, github=github
            )
            if 'resume' in request.FILES:
                profile.resume = request.FILES['resume']
            if 'profile_pic' in request.FILES:
                profile.profile_pic = request.FILES['profile_pic']
            profile.save()

        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    return render(request, 'students/edit_profile.html', {'profile': profile})