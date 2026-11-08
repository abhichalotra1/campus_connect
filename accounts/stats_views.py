"""Statistics page: per-role numbers, rates and chart data."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.shortcuts import render

from accounts.models import User
from placements.models import Application, PlacementDrive


_STATUS_META = [
    ('applied', 'Applied', '#6c63ff'),
    ('shortlisted', 'Shortlisted', '#f5c842'),
    ('selected', 'Selected', '#22d3a0'),
    ('rejected', 'Rejected', '#f43f5e'),
]


def _pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def _plural(n, word):
    return f'{n} {word}' if n == 1 else f'{n} {word}s'


def _status_breakdown(applications):
    """Counts, shares and funnel numbers for a queryset of Applications."""
    raw = {r['status']: r['c'] for r in applications.values('status').annotate(c=Count('id'))}
    total = sum(raw.values())
    rows = [{'key': key, 'label': label, 'color': color,
             'count': raw.get(key, 0), 'pct': _pct(raw.get(key, 0), total)}
            for key, label, color in _STATUS_META]
    shortlisted, selected = raw.get('shortlisted', 0), raw.get('selected', 0)
    forward = shortlisted + selected
    return {
        'rows': rows,
        'total': total,
        'forward': forward,
        'forward_pct': _pct(forward, total),
        'selected_pct': _pct(selected, total),
        'forward_to_selected_pct': _pct(selected, forward),
    }


@login_required
def stats_view(request):
    import json

    user = request.user
    context = {}

    if user.role == 'student':
        my_apps = Application.objects.filter(student=user)
        info = _status_breakdown(my_apps)
        by_key = {r['key']: r['count'] for r in info['rows']}
        context.update(
            total_applied=info['total'], shortlisted=by_key['shortlisted'],
            selected=by_key['selected'], rejected=by_key['rejected'],
            hero_label='Success rate', hero_pct=info['selected_pct'],
        )
        if not info['total']:
            context['insight'] = "You haven't applied to any drive yet. Your first application starts your journey."
        elif by_key['selected']:
            context['insight'] = f"You're selected in {_plural(by_key['selected'], 'drive')}. All that effort paid off."
        elif by_key['shortlisted']:
            context['insight'] = f"{_plural(by_key['shortlisted'], 'application')} shortlisted. You're in the running, so keep your profile sharp."
        else:
            context['insight'] = f"{_plural(info['total'], 'application')} submitted. Recruiters are reviewing, and a few more applications widen your odds."

    elif user.role == 'recruiter':
        my_drives = PlacementDrive.objects.filter(posted_by=user)
        my_apps = Application.objects.filter(drive__in=my_drives)
        info = _status_breakdown(my_apps)
        by_key = {r['key']: r['count'] for r in info['rows']}

        context.update(
            total_drives=my_drives.count(), active_drives=my_drives.open().count(),
            total_applicants=info['total'], shortlisted=by_key['shortlisted'],
            selected=by_key['selected'], rejected=by_key['rejected'],
            hero_label='Hire rate', hero_pct=info['selected_pct'],
        )
        top = my_drives.annotate(app_count=Count('application')).order_by('-app_count', '-id')[:6]
        peak = max([d.app_count for d in top], default=0)
        context['drive_rows'] = [
            {'name': d.role, 'company': d.company, 'count': d.app_count, 'pct': _pct(d.app_count, peak)}
            for d in top
        ]
        if not info['total']:
            context['insight'] = 'No applicants yet. Once students apply, your hiring funnel shows up here.'
        else:
            context['insight'] = (f"{_plural(info['total'], 'applicant')} across "
                                  f"{_plural(context['total_drives'], 'drive')}, and "
                                  f"{info['forward_pct']}% have moved forward.")

    elif user.role == 'admin':
        all_apps = Application.objects.all()
        info = _status_breakdown(all_apps)
        by_key = {r['key']: r['count'] for r in info['rows']}
        total_students = User.objects.filter(role='student').count()
        placed_students = (Application.objects.filter(status='selected')
                           .values('student').distinct().count())

        context.update(
            total_students=total_students,
            total_recruiters=User.objects.filter(role='recruiter').count(),
            total_drives=PlacementDrive.objects.count(),
            total_applications=info['total'],
            selected_students=placed_students,
            placement_rate=round(placed_students / total_students * 100, 1) if total_students else 0,
            hero_label='Placement rate',
            hero_pct=_pct(placed_students, total_students),
        )
        context['insight'] = (f"{placed_students} of {_plural(total_students, 'student')} placed across "
                              f"{_plural(context['total_drives'], 'drive')}.")

        monthly_data = (Application.objects.annotate(month=TruncMonth('applied_at'))
                        .values('month').annotate(count=Count('id')).order_by('month'))
        context['monthly_labels'] = json.dumps([m['month'].strftime('%b %Y') for m in monthly_data if m['month']])
        context['monthly_data'] = json.dumps([m['count'] for m in monthly_data])

        branch_data = (Application.objects.filter(status='selected')
                       .values('student__studentprofile__branch').annotate(count=Count('id')).order_by('-count'))
        context['branch_labels'] = json.dumps([b['student__studentprofile__branch'] or 'N/A' for b in branch_data])
        context['branch_data'] = json.dumps([b['count'] for b in branch_data])
    else:
        info = _status_breakdown(Application.objects.none())

    context['status_rows'] = info['rows']
    context['status_total'] = info['total']
    context['funnel'] = info
    context['status_labels'] = json.dumps([r['label'] for r in info['rows']])
    context['status_data'] = json.dumps([r['count'] for r in info['rows']])
    context['status_colors'] = json.dumps([r['color'] for r in info['rows']])

    return render(request, 'accounts/stats.html', context)
