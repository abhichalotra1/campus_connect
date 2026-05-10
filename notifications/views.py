from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Notification

@login_required
def notification_list_view(request):
    # Show all notifications, but let the user mark them read manually
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')

    return render(request, 'notifications/notifications.html', {
        'notifications': notifications
    })
@login_required
def mark_all_read_view(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('notifications')


@login_required
def mark_read_view(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save()
    
    # FIX: Redirect back to the notifications page
    return redirect('notifications')


def send_notification(user, title, message, notif_type='general'):
    Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notif_type=notif_type
    )