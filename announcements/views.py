from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.decorators import admin_required, is_verified_recruiter
from accounts.notify import notify_admins
from campus_connect.forms_util import flash_form_errors
from campus_connect.pagination import paginate
from .forms import AnnouncementForm
from .models import Announcement
from .services import active_announcements, publish


def _can_send(user):
    return user.role == 'admin' or is_verified_recruiter(user)


@login_required
def announcement_list_view(request):
    """Students: the announcements sent to them. Admins and recruiters: the ones they sent."""
    user = request.user
    if user.role == 'student':
        queryset = active_announcements(
            Announcement.objects.filter(receipts__student=user).select_related('drive', 'author'))
        page, page_query = paginate(request, queryset, per_page=10)
        return render(request, 'announcements/feed.html',
                      {'announcements': page, 'page_obj': page, 'page_query': page_query})

    queryset = Announcement.objects.select_related('drive', 'author')
    if user.role != 'admin':
        queryset = queryset.filter(author=user)
    page, page_query = paginate(request, queryset, per_page=10)
    return render(request, 'announcements/manage.html', {
        'announcements': page, 'page_obj': page, 'page_query': page_query,
        'can_send': _can_send(user),
    })


@login_required
def announcement_create_view(request):
    user = request.user
    if user.role not in ('admin', 'recruiter'):
        messages.error(request, 'Only admins and recruiters can send announcements.')
        return redirect('announcements')
    if not _can_send(user):
        messages.error(request, 'You must be a verified recruiter to send announcements.')
        return redirect('verification_status')

    if request.method == 'POST':
        form = AnnouncementForm(request.POST, user=user)
        if form.is_valid():
            announcement, emailed = publish(form.save())
            log_action(request, 'announcement_sent', announcement.title,
                       f'Announcement #{announcement.pk} to {announcement.audience_label} '
                       f'({announcement.recipients_count} students) by {user.role} {user.username}')
            if user.role == 'recruiter':
                notify_admins('Announcement sent',
                              f'{user.username} sent "{announcement.title}" to '
                              f'{announcement.recipients_count} student(s).')
            messages.success(request, f'Announcement sent to {announcement.recipients_count} student(s).')
            if announcement.send_email and not emailed:
                messages.warning(request, 'Email was skipped because the audience is too large. '
                                          'Students still got it as a notification.')
            return redirect('announcements')
        flash_form_errors(request, form)
    else:
        form = AnnouncementForm(user=user, initial={'audience': 'applicants' if user.role == 'recruiter' else 'all'})

    return render(request, 'announcements/create.html', {'form': form})


@login_required
@require_POST
def announcement_delete_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.user.role != 'admin' and announcement.author_id != request.user.pk:
        messages.error(request, 'Access denied.')
        return redirect('announcements')
    title = announcement.title
    announcement.delete()
    log_action(request, 'announcement_deleted', title, f'Announcement #{pk} deleted by {request.user.username}')
    messages.success(request, 'Announcement deleted.')
    return redirect('announcements')


@admin_required
@require_POST
def announcement_toggle_pin_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    announcement.is_pinned = not announcement.is_pinned
    announcement.save(update_fields=['is_pinned'])
    log_action(request, 'announcement_pinned' if announcement.is_pinned else 'announcement_unpinned',
               announcement.title, f'Announcement #{pk}')
    messages.success(request, 'Announcement pinned.' if announcement.is_pinned else 'Announcement unpinned.')
    return redirect('announcements')
