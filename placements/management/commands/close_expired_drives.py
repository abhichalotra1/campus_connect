from django.core.management.base import BaseCommand
from django.utils import timezone
from placements.models import PlacementDrive

class Command(BaseCommand):
    help = 'Close expired placement drives'

    def handle(self, *args, **kwargs):
        expired = PlacementDrive.objects.filter(
            deadline__lt=timezone.now().date(),
            status='active'
        )
        count = expired.update(status='closed')
        self.stdout.write(f'Closed {count} expired drives.')
