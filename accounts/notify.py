from .models import User


def notify_admins(title, message, notif_type='general', exclude=None):
    """Tell every active admin about something that needs attention (one bulk insert)."""
    from notifications.models import Notification
    admins = User.objects.filter(role='admin', is_active=True)
    if exclude is not None:
        admins = admins.exclude(pk=exclude.pk)
    Notification.objects.bulk_create(
        [Notification(user=a, title=title, message=message, notif_type=notif_type) for a in admins])
