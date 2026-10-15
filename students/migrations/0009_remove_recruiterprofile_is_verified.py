from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0008_approve_verified_recruiters'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='recruiterprofile',
            name='is_verified',
        ),
    ]
