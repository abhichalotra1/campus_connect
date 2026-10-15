from django.db import migrations
from django.utils import timezone


def approve_verified(apps, schema_editor):
    """Before is_verified becomes derived from verification_status, make sure every
    recruiter who was verified under the old flag is marked 'approved'."""
    RecruiterProfile = apps.get_model('students', 'RecruiterProfile')
    for profile in RecruiterProfile.objects.filter(is_verified=True).exclude(verification_status='approved'):
        profile.verification_status = 'approved'
        if profile.verified_at is None:
            profile.verified_at = timezone.now()
        profile.save(update_fields=['verification_status', 'verified_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0007_alter_recruiterprofile_profile_pic_and_more'),
    ]

    operations = [
        migrations.RunPython(approve_verified, migrations.RunPython.noop),
    ]
