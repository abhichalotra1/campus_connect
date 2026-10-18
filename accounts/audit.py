import logging

from .models import AuditLog

logger = logging.getLogger(__name__)


def _client_ip(request):
    # Render sits behind one proxy; the last X-Forwarded-For entry is the one it added.
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[-1].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def log_action(request, action, target='', details=''):
    """Record an audit entry. Never lets a logging failure break the request."""
    try:
        AuditLog.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            action=action,
            target=str(target)[:200],
            details=details,
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.exception('Audit log write failed for action=%s', action)
