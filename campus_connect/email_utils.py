from django.core.mail import send_mail
from django.conf import settings

def send_application_email(student, drive):
    send_mail(
        subject=f'Application Received - {drive.company}',
        message=f'''Dear {student.first_name},

Your application for {drive.role} at {drive.company} has been received successfully!

We will notify you once the recruiter reviews your application.

Details:
- Company: {drive.company}
- Role: {drive.role}
- Package: {drive.package}
- Deadline: {drive.deadline}

Best of luck!
The Campus Connect Team''',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[student.email],
        fail_silently=True,
    )


def send_status_update_email(student, drive, status):
    status_messages = {
        'shortlisted': f'Congratulations! You have been SHORTLISTED for {drive.role} at {drive.company}!',
        'selected':    f'Congratulations! You have been SELECTED for {drive.role} at {drive.company}!',
        'rejected':    f'We regret to inform you that your application for {drive.role} at {drive.company} was not successful this time.',
    }

    message = status_messages.get(status, f'Your application status has been updated to {status}')

    send_mail(
        subject=f'Application Update - {drive.company}',
        message=f'''Dear {student.first_name},

{message}

Keep applying and never give up!

Best Regards,
The Campus Connect Team''',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[student.email],
        fail_silently=True,
    )


def send_recruiter_email(recruiter, student, drive):
    send_mail(
        subject=f'New Application - {drive.role}',
        message=f'''Dear {recruiter.first_name},

A new student has applied for your placement drive!

Student Details:
- Name: {student.get_full_name()}
- Email: {student.email}
- Username: {student.username}

Drive Details:
- Role: {drive.role}
- Company: {drive.company}

Login to Campus Connect admin panel to review and update application status.

The Campus Connect Team''',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recruiter.email],
        fail_silently=True,
    )


def send_interview_email(student, drive, scheduled_at, location, meeting_link, notes):
    send_mail(
        subject=f'Interview Scheduled - {drive.company}',
        message=f'''Dear {student.first_name},

Your interview has been scheduled!

Details:
- Company: {drive.company}
- Role: {drive.role}
- Date & Time: {scheduled_at}
- Location: {location}
- Meeting Link: {meeting_link if meeting_link else 'Will be shared later'}

Notes: {notes if notes else 'No additional notes'}

Please be on time and all the best!

The Campus Connect Team''',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[student.email],
        fail_silently=True,
    )