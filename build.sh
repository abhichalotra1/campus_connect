#!/bin/bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate

# Auto-create missing profiles for existing users
python3 manage.py shell -c "
from accounts.models import User
from students.models import StudentProfile, RecruiterProfile
for user in User.objects.all():
    if user.role == 'student':
        StudentProfile.objects.get_or_create(user=user, defaults={'branch': 'CSE', 'roll_number': 'N/A', 'passing_year': 2025})
    elif user.role == 'recruiter':
        RecruiterProfile.objects.get_or_create(user=user)
print('Profiles fixed!')
"