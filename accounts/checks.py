import os

from django.conf import settings
from django.core.checks import Warning, register


@register()
def uploads_need_persistent_storage(app_configs, **kwargs):
    """On Render the local disk is wiped each deploy: warn if uploads are not on Cloudinary."""
    on_render = bool(os.getenv('RENDER'))
    backend = settings.STORAGES['default']['BACKEND']
    if on_render and 'Cloudinary' not in backend:
        return [Warning(
            'Uploads (resumes, pictures, logos) are stored on the local disk, which Render erases '
            'on every deploy and does not serve when DEBUG is off.',
            hint='Set the CLOUDINARY_URL environment variable (see DEPLOY.md).',
            id='campus_connect.W001',
        )]
    return []
