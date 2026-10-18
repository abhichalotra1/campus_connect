from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_auditlog'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='is_verified',
        ),
    ]
