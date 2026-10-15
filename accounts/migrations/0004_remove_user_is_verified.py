from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_remove_user_last_active_at'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='is_verified',
        ),
    ]
