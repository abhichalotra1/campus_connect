from django.utils import timezone
from placements.models import PlacementDrive

def close_expired_drives():
    PlacementDrive.objects.filter(
        deadline__lt=timezone.now().date(),
        status='active'
    ).update(status='closed')
