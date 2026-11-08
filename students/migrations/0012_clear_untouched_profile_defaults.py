from django.db import migrations
from django.db.models import Q


def clear_untouched_defaults(apps, schema_editor):
    """Profiles nobody ever filled in were auto-created as branch=CSE, passing_year=<that year>.

    Blank those two so the new profile-complete check is honest. A profile counts as untouched
    only if every other field is empty too, so nobody's real data is lost.
    """
    StudentProfile = apps.get_model('students', 'StudentProfile')
    (StudentProfile.objects
        .filter(cgpa=0, skills='', about='', certifications='', linkedin='', github='')
        .filter(Q(resume='') | Q(resume__isnull=True))
        .filter(Q(roll_number__isnull=True) | Q(roll_number=''))
        .update(branch='', passing_year=None))


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0011_profile_fields_optional'),
    ]

    operations = [
        migrations.RunPython(clear_untouched_defaults, migrations.RunPython.noop),
    ]
