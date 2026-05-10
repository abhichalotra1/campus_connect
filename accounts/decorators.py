# accounts/decorators.py

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def recruiter_required(view_func):
    """Allow only logged-in recruiters."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role != 'recruiter':
            messages.error(request, 'This area is for recruiters only.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def verified_recruiter_required(view_func):
    """Allow only logged-in AND verified recruiters."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role != 'recruiter':
            messages.error(request, 'This area is for recruiters only.')
            return redirect('dashboard')
        try:
            profile = request.user.recruiterprofile
            if not profile.is_verified:
                # Send to verification status page instead of crashing
                return redirect('verification_status')
        except Exception:
            return redirect('verification_status')
        return view_func(request, *args, **kwargs)
    return wrapper


def student_required(view_func):
    """Allow only logged-in students."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role != 'student':
            messages.error(request, 'This area is for students only.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper