# accounts/decorators.py

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """Allow only logged-in admins (one place for the rule instead of copy-pasted checks)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role != 'admin':
            messages.error(request, 'Access denied.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def is_verified_recruiter(user):
    """True for an authenticated recruiter whose account an admin has approved."""
    if not user.is_authenticated or user.role != 'recruiter':
        return False
    profile = getattr(user, 'recruiterprofile', None)  # missing profile -> None
    return bool(profile and profile.is_verified)
